"""Startup checks and health snapshots for the API process."""
from __future__ import annotations

import os
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


def _check_postgres() -> dict[str, Any]:
    try:
        from sqlalchemy import text

        from backend.db.session import engine

        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"ok": True, "detail": "reachable"}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def _check_redis() -> dict[str, Any]:
    try:
        import redis

        client = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379/0"),
            socket_connect_timeout=2,
        )
        client.ping()
        return {"ok": True, "detail": "reachable"}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}


def health_snapshot() -> tuple[dict[str, Any], bool]:
    """Return (payload, overall_ok). Never raises."""
    postgres = _check_postgres()
    redis_status = _check_redis()
    overall = bool(postgres.get("ok") and redis_status.get("ok"))
    payload = {
        "status": "ok" if overall else "degraded",
        "postgres": postgres,
        "redis": redis_status,
    }
    return payload, overall


def run_startup_checks() -> None:
    """Log dependency health at process start. Does not abort boot."""
    payload, overall = health_snapshot()
    if overall:
        logger.info("startup_checks_ok", **payload)
    else:
        logger.warning("startup_checks_degraded", **payload)
