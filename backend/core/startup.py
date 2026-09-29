"""
Startup validation for financial-research-agent.

Called by FastAPI lifespan and Celery worker_process_init.
Raises RuntimeError with a clear message if any required condition
is not met, so the process fails fast rather than crashing mid-request.

Some checks are warn-only (schema drift, model cache, MLflow dir) since
they don't prevent the app from serving requests.
"""
import os
from pathlib import Path
from typing import Tuple

import structlog

logger = structlog.get_logger(__name__)

REQUIRED_ENV_VARS = [
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "GROQ_API_KEY",
    "NEWSAPI_KEY",
    "REDIS_URL",
]

BGE_MODEL_DIR_FRAGMENT = "models--BAAI--bge-large-en-v1.5"


def _check_env() -> None:
    missing = [v for v in REQUIRED_ENV_VARS if not os.getenv(v)]
    if missing:
        raise RuntimeError(
            "missing required env var(s): " + ", ".join(missing)
        )


def _check_postgres() -> None:
    from sqlalchemy import text
    from backend.db.session import engine

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        raise RuntimeError(f"PostgreSQL unreachable: {e}") from e


def _check_schema_current() -> None:
    """Warn (don't fail) if the DB is behind the latest migration head."""
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        from backend.db.session import engine

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        heads = set(script.get_heads())
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        if current not in heads:
            logger.critical(
                "schema_out_of_date", current=current, head=list(heads),
                hint="run `alembic upgrade head`",
            )
    except Exception as e:
        logger.warning("schema_check_failed", error=str(e))


def _check_redis() -> None:
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=3, socket_timeout=3)
        client.ping()
    except Exception as e:
        raise RuntimeError(f"Redis unreachable: {e}") from e


def _check_groq_key() -> None:
    key = os.getenv("GROQ_API_KEY", "")
    if not (key.startswith("gsk_") and len(key) > 20):
        raise RuntimeError("GROQ_API_KEY format invalid (expected 'gsk_...' len > 20)")


def _log_groq_model() -> None:
    from backend.core.groq_config import get_groq_model

    logger.info("groq_model", model=get_groq_model())


def _hf_cache_dir() -> Path:
    return Path(
        os.getenv("HF_HOME")
        or os.getenv("TRANSFORMERS_CACHE")
        or (Path.home() / ".cache" / "huggingface")
    )


def _check_model_cache() -> None:
    """Warn-only: BGE model files present in the HF cache?"""
    cache = _hf_cache_dir()
    hub = cache / "hub"
    found = (hub / BGE_MODEL_DIR_FRAGMENT).exists() or (
        cache / BGE_MODEL_DIR_FRAGMENT
    ).exists()
    if not found:
        logger.warning(
            "bge_model_not_cached",
            hint="first embedding run will download ~1.3GB",
            cache_dir=str(cache),
        )


def _check_mlflow_dir() -> None:
    """Warn-only: MLflow tracking dir exists and is writable."""
    uri = os.getenv("MLFLOW_TRACKING_URI", "mlruns")
    path = Path(uri.replace("file:", "")) if not uri.startswith("http") else None
    if path is None:
        return
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write_test"
        probe.touch()
        probe.unlink()
    except Exception as e:
        logger.warning("mlflow_dir_not_writable", path=str(path), error=str(e))


def run_startup_checks() -> None:
    """Run all checks; raise RuntimeError on the first hard failure."""
    logger.info("startup_checks_begin")
    _check_env()            # hard
    _check_postgres()       # hard
    _check_redis()          # hard
    _check_groq_key()       # hard
    _log_groq_model()
    _check_schema_current()  # warn
    _check_model_cache()     # warn
    _check_mlflow_dir()      # warn
    logger.info("startup_checks_passed")


# ── /health support (must never raise) ───────────────────────────────
def _git_commit_short() -> str:
    try:
        import subprocess

        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"])
            .decode()
            .strip()[:8]
        )
    except Exception:
        return "unknown"


def health_snapshot() -> Tuple[dict, bool]:
    """
    Build the /health payload without raising. Returns (payload, ok) where
    ok is False if any hard dependency is degraded.
    """
    payload = {
        "status": "ok",
        "postgres": "ok",
        "redis": "ok",
        "groq_key": "ok",
        "model_cache": "ok",
        "version": _git_commit_short(),
    }
    ok = True

    try:
        _check_postgres()
    except Exception:
        payload["postgres"] = "error"
        ok = False

    try:
        _check_redis()
    except Exception:
        payload["redis"] = "error"
        ok = False

    key = os.getenv("GROQ_API_KEY", "")
    if not (key.startswith("gsk_") and len(key) > 20):
        payload["groq_key"] = "missing"
        ok = False

    cache = _hf_cache_dir()
    hub = cache / "hub"
    if not ((hub / BGE_MODEL_DIR_FRAGMENT).exists() or (cache / BGE_MODEL_DIR_FRAGMENT).exists()):
        payload["model_cache"] = "missing"

    payload["status"] = "ok" if ok else "degraded"
    return payload, ok
