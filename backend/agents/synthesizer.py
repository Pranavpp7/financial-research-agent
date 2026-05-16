"""
Synthesizer: combines specialist analyses into a final report.
Calls Groq in JSON mode, parses, and persists to reports + report_citations.
"""
import json
import os

from dotenv import load_dotenv
from groq import Groq

from backend.agents.prompts import SYNTHESIS_PROMPT
from backend.db.crud import save_report
from backend.db.models import ReportCitation
from backend.db.session import SessionLocal

load_dotenv()


SYNTHESIZER_MODEL = "llama-3.3-70b-versatile"


class Synthesizer:
    def __init__(self, model: str = SYNTHESIZER_MODEL):
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY not set in .env")
        self.client = Groq(api_key=api_key)
        self.model = model

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
            return {"error": f"synthesis returned invalid JSON: {e}", "raw": raw}
        except Exception as e:
            return {"error": f"synthesis call failed: {e}"}

        # Persist
        db = SessionLocal()
        try:
            report = save_report(db, company_id, {
                "bull_case": report_data.get("bull_case", ""),
                "bear_case": report_data.get("bear_case", ""),
                "risk_level": report_data.get("risk_level", "medium"),
                "overall_sentiment": None,
                "confidence_score": float(report_data.get("confidence_score", 0.0)),
                "sources": report_data.get("sources", []),
            })
            # One ReportCitation row per key_finding -- the synthesis prompt
            # doesn't link claims to specific source IDs, so source_type is
            # always "synthesis" and source_id stays null. Refine later if
            # the prompt is upgraded to emit per-claim citations.
            confidence = float(report_data.get("confidence_score", 0.0))
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
        finally:
            db.close()

        return report_data
