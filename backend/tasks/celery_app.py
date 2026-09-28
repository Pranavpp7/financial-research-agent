"""
Celery application: Redis broker + Redis result backend.

Worker:
  celery -A backend.tasks.celery_app worker --loglevel=info --pool=threads

On Windows the default prefork pool can hang on `fork()`; --pool=threads
or --pool=solo is the safe choice. solo = single-threaded (most reliable);
threads = N concurrent tasks per worker.

Flower (monitoring dashboard):
  celery -A backend.tasks.celery_app flower --port=5555
"""
import os

from celery import Celery
from celery.signals import worker_init, worker_process_init
from dotenv import load_dotenv

from backend.core.logging import configure_logging

load_dotenv()


# worker_process_init covers prefork pool children (production); worker_init
# covers the main process, which is the only one under --pool=threads/solo
# (the documented dev command on Windows).
@worker_init.connect
@worker_process_init.connect
def _configure_worker_logging(**_kwargs) -> None:
    """Set up structlog in each Celery worker process at startup."""
    configure_logging()


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "financial_research_agent",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "backend.tasks.analysis_tasks",
        "backend.tasks.scheduled_tasks",
        "backend.tasks.backtest_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    # one analysis can take 30s+; keep results around long enough to poll
    result_expires=3600,
    # All tasks publish to (and workers consume) this queue. Must match the
    # `-Q analysis` flag on the worker service in docker-compose.prod.yml —
    # without this, tasks go to the default "celery" queue and a `-Q analysis`
    # worker never picks them up.
    task_default_queue="analysis",
)

# ── Celery beat schedule ─────────────────────────────────────────────
# IMPORTANT: run exactly ONE beat process (the `beat` service in
# docker-compose.prod.yml). Celery beat is not multi-instance safe by
# default -- multiple beats would double-fire every scheduled task.
from celery.schedules import crontab  # noqa: E402

celery_app.conf.beat_schedule = {
    "nightly-watchlist-reanalysis": {
        "task": "scheduled_watchlist_analysis",
        "schedule": crontab(hour=2, minute=0),  # 2 AM UTC daily
    },
    "weekly-batch-ingestion": {
        "task": "scheduled_batch_ingestion",
        "schedule": crontab(hour=1, minute=0, day_of_week=0),  # Sunday 1 AM UTC
    },
    "beat-heartbeat": {
        "task": "beat_heartbeat",
        "schedule": 60.0,  # every minute, for /schedule/status liveness
    },
}
