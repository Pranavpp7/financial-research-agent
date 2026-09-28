"""Celery task wrapping the (long-running) backtest engine."""
import structlog

from backend.backtesting.engine import run_backtest
from backend.tasks.celery_app import celery_app

logger = structlog.get_logger(__name__)


@celery_app.task(name="run_backtest", bind=True)
def run_backtest_task(
    self,
    name: str,
    tickers: list[str] | None = None,
    min_confidence: float = 0.0,
) -> dict:
    """Run a backtest, streaming per-report progress via update_state."""
    def progress(meta: dict) -> None:
        self.update_state(state="PROGRESS", meta=meta)

    logger.info("backtest_task_received", name=name, task_id=self.request.id)
    try:
        run_id = run_backtest(name, tickers, min_confidence, progress_cb=progress)
        return {"backtest_run_id": run_id}
    except Exception as e:
        logger.error("backtest_task_failed", name=name, error=str(e))
        return {"error": str(e)}
