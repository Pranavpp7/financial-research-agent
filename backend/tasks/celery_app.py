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
from dotenv import load_dotenv

load_dotenv()


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "financial_research_agent",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=["backend.tasks.analysis_tasks"],
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
)
