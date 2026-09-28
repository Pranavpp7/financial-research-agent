"""Celery tasks that wrap the agent pipeline."""
import os

import structlog

from backend.agents.run_agent import analyze
from backend.core.cache import find_fresh_report, make_cache_key, report_to_dict
from backend.core.rate_limiter import RateLimitExceeded
from backend.db.models import Report
from backend.db.session import SessionLocal
from backend.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="run_analysis", bind=True, max_retries=3)
def run_analysis_task(
    self, ticker: str, question: str, force_refresh: bool = False
) -> dict:
    """
    Run the full supervisor -> analyzer -> synthesizer pipeline.

    Caching: unless force_refresh, a sufficiently fresh report
    (CACHE_TTL_MINUTES, default 360) for the same (ticker, question) is
    returned without spending Groq tokens. Fresh runs persist cache_key
    and question on the new report row.

    Streams stage progress via `self.update_state(state="PROGRESS", ...)`.
    On RateLimitExceeded the task auto-retries up to max_retries, then
    returns a structured rate-limit error. Other exceptions return
    {"error": ...}.
    """
    def progress(meta: dict) -> None:
        self.update_state(state="PROGRESS", meta=meta)

    logger.info(
        "task_received", ticker=ticker, task_id=self.request.id,
        force_refresh=force_refresh,
    )

    ttl = int(os.getenv("CACHE_TTL_MINUTES", "360"))

    # ── Cache check ──
    if not force_refresh:
        db = SessionLocal()
        try:
            cached = find_fresh_report(db, ticker, question, ttl)
            if cached:
                logger.info(
                    "cache_hit", ticker=ticker, report_id=cached.id,
                    age_minutes=cached.age_minutes,
                )
                self.update_state(state="PROGRESS", meta={
                    "stage": "cache_hit",
                    "message": "Returning cached report",
                    "pct": 100,
                })
                return report_to_dict(db, cached, from_cache=True)
        finally:
            db.close()

    try:
        result = analyze(ticker, question, progress_cb=progress)
        # Persist cache_key + question on the freshly created report row.
        rid = result.get("report_id")
        if rid:
            db = SessionLocal()
            try:
                report = db.query(Report).filter(Report.id == rid).first()
                if report:
                    report.cache_key = make_cache_key(ticker, question)
                    report.question = question
                    db.commit()
            finally:
                db.close()
        result["from_cache"] = False
        logger.info("task_complete", ticker=ticker, task_id=self.request.id,
                    report_id=result.get("report_id"), error=result.get("error"))
        return result
    except RateLimitExceeded as e:
        logger.warning(
            "task_rate_limited", ticker=ticker, task_id=self.request.id,
            service=e.service, retry_after_seconds=e.retry_after_seconds,
        )
        try:
            # Re-queue after the limiter says a slot frees up.
            raise self.retry(countdown=e.retry_after_seconds, max_retries=3)
        except self.MaxRetriesExceededError:
            return {
                "error": "rate_limit_exceeded",
                "service": e.service,
                "retry_after_seconds": e.retry_after_seconds,
                "message": (
                    f"{e.service} rate limit reached and automatic retries "
                    f"are exhausted. Try again in ~{e.retry_after_seconds}s."
                ),
            }
    except Exception as e:
        logger.error("task_failed", ticker=ticker, task_id=self.request.id, error=str(e))
        return {
            "error": str(e),
            "ticker": ticker,
            "question": question,
        }
