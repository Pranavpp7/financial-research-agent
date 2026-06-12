"""
FastAPI application.

Run:
  uvicorn backend.api.main:app --reload --port 8000

Requires a Celery worker for /analyze to actually process tasks:
  celery -A backend.tasks.celery_app worker --loglevel=info --pool=threads
"""
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import redis
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func

from backend.api.routes import alerts, analysis, backtest, watchlist
from backend.core.logging import configure_logging
from backend.core.rate_limiter import GROQ, NEWSAPI, get_rate_limiter
from backend.core.startup import health_snapshot, run_startup_checks
from backend.db.models import Report, ScheduledRun
from backend.db.session import SessionLocal

# Configure structured logging before the app handles any request.
configure_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    run_startup_checks()
    yield


app = FastAPI(
    title="Financial Research Agent API",
    description=(
        "Multi-source financial analysis: SEC filings (RAG), earnings, news "
        "sentiment, ML risk models, synthesized via Groq Llama 3.3 70B."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# CORS. `allow_origins=["*"]` is invalid alongside `allow_credentials=True`
# (browsers reject the wildcard for credentialed requests), so origins are
# an explicit allowlist — configurable via CORS_ORIGINS (comma-separated),
# defaulting to the local Vite/React dev servers.
_cors_origins = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:5173,http://localhost:3000"
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(analysis.router)
app.include_router(watchlist.router)
app.include_router(alerts.router)
app.include_router(backtest.router)


@app.get("/")
def root():
    return {
        "name": "Financial Research Agent API",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": [
            "GET  /health",
            "POST /analyze",
            "GET  /analyze/{task_id}",
            "GET  /reports/{ticker}",
            "GET  /companies",
        ],
    }


@app.get("/health")
def health():
    """Dependency health for Docker healthchecks. Never raises."""
    payload, _ok = health_snapshot()
    return payload


@app.get("/schedule/status")
def schedule_status():
    """Beat liveness, next scheduled runs, and last-run summaries."""
    # Beat liveness via the heartbeat Redis key (refreshed every minute).
    beat_running = False
    try:
        client = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=2,
        )
        beat_running = client.get("beat:heartbeat") is not None
    except Exception:
        beat_running = False

    now = datetime.now(timezone.utc)

    def _next_daily(hour: int, minute: int) -> str:
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if cand <= now:
            cand += timedelta(days=1)
        return cand.isoformat()

    def _next_weekly(weekday_py: int, hour: int, minute: int) -> str:
        # weekday_py: Monday=0 .. Sunday=6
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        days_ahead = (weekday_py - now.weekday()) % 7
        cand += timedelta(days=days_ahead)
        if cand <= now:
            cand += timedelta(days=7)
        return cand.isoformat()

    next_runs = {
        "nightly-watchlist-reanalysis": _next_daily(2, 0),
        "weekly-batch-ingestion": _next_weekly(6, 1, 0),  # Sunday 01:00 UTC
    }

    db = SessionLocal()
    try:
        last_runs: dict = {}
        for name in ("nightly-watchlist-reanalysis", "weekly-batch-ingestion"):
            row = (
                db.query(ScheduledRun)
                .filter(ScheduledRun.task_name == name)
                .order_by(ScheduledRun.ran_at.desc())
                .first()
            )
            if row:
                entry = {
                    "ran_at": row.ran_at.isoformat() if row.ran_at else None,
                    "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                    "status": row.status,
                }
                if isinstance(row.summary, dict):
                    entry.update(row.summary)
                last_runs[name] = entry
    finally:
        db.close()

    return {
        "beat_running": beat_running,
        "next_runs": next_runs,
        "last_runs": last_runs,
    }


@app.get("/cache/stats")
def cache_stats():
    """Report-cache stats. hit_rate / savings need an llm_usage table that
    does not exist yet, so those fields are null."""
    db = SessionLocal()
    try:
        cached_count = (
            db.query(func.count(Report.id))
            .filter(Report.cache_key.isnot(None))
            .scalar()
            or 0
        )
    finally:
        db.close()
    return {
        "cache_ttl_minutes": int(os.getenv("CACHE_TTL_MINUTES", "360")),
        "cached_reports_count": int(cached_count),
        "hit_rate_24h": None,
        "estimated_savings_usd_24h": None,
    }


@app.get("/rate-limits")
def rate_limits():
    """Current remaining quota for the external APIs (internal use)."""
    limiter = get_rate_limiter()
    return {
        "newsapi": {
            "remaining_today": limiter.get_remaining(NEWSAPI),
            "limit": limiter.newsapi_daily_limit,
        },
        "groq": {
            "remaining_this_minute": limiter.get_remaining(GROQ),
            "limit": limiter.groq_rpm_limit,
        },
    }
