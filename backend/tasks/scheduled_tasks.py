"""
Celery beat-scheduled tasks for financial-research-agent.

Nightly: re-analyze every ticker on the watchlist with the default
question, using cache (so repeated runs within TTL are skipped).

Weekly: refresh ingestion data for all watchlist companies (yfinance, SEC,
NewsAPI) so the next nightly analysis runs on fresh data.

A lightweight `beat_heartbeat` task lets /schedule/status detect whether
beat is alive (it refreshes a short-TTL Redis key each minute).

Each scheduled task writes a `scheduled_runs` row on completion so the API
can report last-run summaries.
"""
import os
from datetime import datetime, timezone

import structlog

from backend.db.models import ScheduledRun, Watchlist, utcnow
from backend.db.session import SessionLocal
from backend.tasks.analysis_tasks import run_analysis_task
from backend.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)

BEAT_HEARTBEAT_KEY = "beat:heartbeat"
BEAT_HEARTBEAT_TTL = 120  # seconds

DEFAULT_QUESTION_TEMPLATE = (
    "Provide a comprehensive analysis of {ticker} covering earnings, "
    "risk, and recent news."
)


def _watchlist_tickers() -> list[str]:
    db = SessionLocal()
    try:
        return [w.ticker for w in db.query(Watchlist).all()]
    finally:
        db.close()


def _start_run(task_name: str) -> int:
    db = SessionLocal()
    try:
        row = ScheduledRun(
            task_name=task_name,
            ran_at=utcnow(),
            status="running",
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row.id
    finally:
        db.close()


def _finish_run(run_id: int, status: str, summary: dict, error: str | None = None) -> None:
    db = SessionLocal()
    try:
        row = db.query(ScheduledRun).filter(ScheduledRun.id == run_id).first()
        if row:
            row.status = status
            row.summary = summary
            row.error = error
            row.completed_at = utcnow()
            db.commit()
    finally:
        db.close()


def _stamp_last_analyzed(ticker: str) -> None:
    db = SessionLocal()
    try:
        w = db.query(Watchlist).filter(Watchlist.ticker == ticker).first()
        if w:
            w.last_analyzed_at = utcnow()
            db.commit()
    finally:
        db.close()


@celery_app.task(name="beat_heartbeat")
def beat_heartbeat() -> None:
    """Refresh a short-TTL Redis key so /schedule/status can detect beat."""
    try:
        import redis

        client = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=2,
        )
        client.set(
            BEAT_HEARTBEAT_KEY,
            datetime.now(timezone.utc).isoformat(),
            ex=BEAT_HEARTBEAT_TTL,
        )
    except Exception as e:
        logger.warning("beat_heartbeat_failed", error=str(e))


@celery_app.task(name="scheduled_watchlist_analysis")
def scheduled_watchlist_analysis() -> dict:
    """Re-analyze every watchlist ticker with the default question (cached)."""
    run_id = _start_run("nightly-watchlist-reanalysis")
    tickers = _watchlist_tickers()
    summary = {
        "tickers_processed": 0,
        "cache_hits": 0,
        "new_reports": 0,
        "failed": 0,
        "by_ticker": {},
    }
    logger.info("nightly_reanalysis_start", count=len(tickers))
    try:
        for ticker in tickers:
            question = DEFAULT_QUESTION_TEMPLATE.format(ticker=ticker)
            # Run the task logic synchronously (eager) so we get the result
            # dict and can record an accurate outcome. force_refresh=False so
            # the cache absorbs duplicates within the TTL window.
            try:
                result = run_analysis_task.apply(
                    args=[ticker, question, False]
                ).result
                if isinstance(result, dict) and result.get("error"):
                    summary["failed"] += 1
                    outcome = "failed"
                elif isinstance(result, dict) and result.get("from_cache"):
                    summary["cache_hits"] += 1
                    outcome = "cache_hit"
                else:
                    summary["new_reports"] += 1
                    outcome = "new_report"
                _stamp_last_analyzed(ticker)
            except Exception as e:
                summary["failed"] += 1
                outcome = "failed"
                logger.error("nightly_ticker_failed", ticker=ticker, error=str(e))
            summary["tickers_processed"] += 1
            summary["by_ticker"][ticker] = outcome
            logger.info("nightly_ticker_done", ticker=ticker, outcome=outcome)
        _finish_run(run_id, "completed", summary)
        return summary
    except Exception as e:
        logger.error("nightly_reanalysis_failed", error=str(e))
        _finish_run(run_id, "failed", summary, error=str(e))
        raise


@celery_app.task(name="scheduled_batch_ingestion")
def scheduled_batch_ingestion() -> dict:
    """Refresh ingestion data for all watchlist tickers (not the dev seed)."""
    run_id = _start_run("weekly-batch-ingestion")
    tickers = _watchlist_tickers()
    logger.info("weekly_ingestion_start", count=len(tickers))
    try:
        if not tickers:
            summary = {"succeeded": [], "failed": [], "note": "watchlist empty"}
            _finish_run(run_id, "completed", summary)
            return summary
        from backend.ingestion.pipeline import run_batch_ingestion

        result = run_batch_ingestion(tickers)  # rate limiter handles NewsAPI
        summary = {
            "succeeded": result.get("succeeded", []),
            "failed": result.get("failed", []),
        }
        _finish_run(run_id, "completed", summary)
        return summary
    except Exception as e:
        logger.error("weekly_ingestion_failed", error=str(e))
        _finish_run(run_id, "failed", {}, error=str(e))
        raise
