"""
Synthesizer: combines specialist analyses into a final report.
Calls Groq in JSON mode, parses, and persists to reports + report_citations.
"""
import json
import os

import structlog
from dotenv import load_dotenv
from groq import Groq

from backend.agents.prompts import SYNTHESIS_PROMPT
from backend.core.groq_config import get_groq_model
from backend.core.rate_limiter import get_rate_limiter
from backend.db.crud import save_report
from backend.db.models import ReportCitation
from backend.db.session import SessionLocal

load_dotenv()

logger = structlog.get_logger(__name__)


def _clamp_unit(value, default: float = 0.0) -> float:
    """Coerce an LLM-supplied number into [0.0, 1.0]; fall back on garbage."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


class Synthesizer:
    def __init__(self, model: str | None = None):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        self.client = Groq(api_key=api_key)
        self.model = model or get_groq_model()

    def synthesize(
        self, ticker: str, company_id: int, analyses: list[dict]
    ) -> dict:
        # Format analyses as one big context block
        blocks = []
        for a in analyses:
            header = f"[{a['type'].upper()} ANALYSIS]"
            if a.get("error"):
                blocks.append(f"{header}\nERROR: {a['error']}")
            else:
                blocks.append(f"{header}\n{a['text']}")
        context = "\n\n---\n\n".join(blocks)

        # Call LLM in JSON mode
        logger.info("synthesis_start", ticker=ticker, n_analyses=len(analyses))
        # Acquire OUTSIDE the try: RateLimitExceeded must propagate to the
        # Celery task's retry handler; the generic except below would turn
        # it into a plain error report instead.
        get_rate_limiter().acquire("groq")
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": SYNTHESIS_PROMPT},
                    {"role": "user", "content": (
                        f"Ticker: {ticker}\n\n"
                        f"Specialist analyses:\n\n{context}\n\n"
                        "Produce the JSON report now."
                    )},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            report_data = json.loads(raw)
        except json.JSONDecodeError as e:
            logger.error("synthesis_json_error", ticker=ticker, error=str(e))
            return {"error": f"synthesis returned invalid JSON: {e}", "raw": raw}
        except Exception as e:
            logger.error("synthesis_call_failed", ticker=ticker, error=str(e))
            return {"error": f"synthesis call failed: {e}"}

        # Parse + clamp numeric fields. The LLM may omit or mis-type them
        # (e.g. confidence_score: "high"), so coerce defensively into [0, 1].
        data_quality = _clamp_unit(report_data.get("data_quality"))
        confidence = _clamp_unit(report_data.get("confidence_score"))
        analyst_notes = report_data.get("analyst_notes") or ""
        # Write the clamped/normalized values back so the returned dict and
        # the persisted row agree.
        report_data["data_quality"] = data_quality
        report_data["confidence_score"] = confidence
        report_data["analyst_notes"] = analyst_notes

        # Persist
        db = SessionLocal()
        try:
            report = save_report(db, company_id, {
                "bull_case": report_data.get("bull_case", ""),
                "bear_case": report_data.get("bear_case", ""),
                "risk_level": report_data.get("risk_level", "medium"),
                "overall_sentiment": None,
                "confidence_score": confidence,
                "data_quality": data_quality,
                "analyst_notes": analyst_notes,
                "sources": report_data.get("sources", []),
            })
            # One ReportCitation row per key_finding -- the synthesis prompt
            # doesn't link claims to specific source IDs, so source_type is
            # always "synthesis" and source_id stays null. Refine later if
            # the prompt is upgraded to emit per-claim citations.
            for finding in report_data.get("key_findings", []):
                db.add(ReportCitation(
                    report_id=report.id,
                    claim_text=finding,
                    source_type="synthesis",
                    source_id=None,
                    confidence=confidence,
                ))
            db.commit()
            report_data["report_id"] = report.id

            # Fire risk-transition alerts (must never break the pipeline).
            from backend.core.alerts import dispatch_alerts
            try:
                dispatch_alerts(db, report)
            except Exception as e:
                logger.error("alert_dispatch_failed", error=str(e), report_id=report.id)
        finally:
            db.close()

        logger.info(
            "synthesis_complete", ticker=ticker,
            report_id=report_data.get("report_id"),
            risk_level=report_data.get("risk_level"),
            data_quality=report_data.get("data_quality"),
        )
        return report_data
