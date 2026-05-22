"""
Non-destructive health check for the financial-research-agent stack.

Verifies that everything is wired up and reachable WITHOUT mutating data,
calling paid LLM APIs, or downloading models:

  1. ENV       -- required env vars are present (values are masked)
  2. IMPORTS   -- every key module imports cleanly (catches wiring bugs)
  3. DEPS      -- optional-but-needed libs (httpx for the API smoke test)
  4. POSTGRES  -- DB reachable + Alembic at head
  5. REDIS     -- broker reachable (PING)
  6. MIGRATIONS-- single linear head

Exit code is non-zero if any CRITICAL check fails. Service checks
(Postgres/Redis) are reported but treated as WARN, since you may run this
before `docker compose up`.

Usage:
  uv run --module scripts.healthcheck
  uv run python scripts/healthcheck.py
"""
import importlib
import os
import sys
from pathlib import Path

# Allow `python scripts/healthcheck.py` as well as `-m scripts.healthcheck`
# by ensuring the repo root (parent of scripts/) is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()

OK = "PASS"
WARN = "WARN"
FAIL = "FAIL"

results: list[tuple[str, str, str]] = []  # (status, name, detail)
critical_failed = False


def record(status: str, name: str, detail: str = "") -> None:
    global critical_failed
    if status == FAIL:
        critical_failed = True
    results.append((status, name, detail))
    icon = {OK: "[PASS]", WARN: "[WARN]", FAIL: "[FAIL]"}[status]
    line = f"  {icon} {name}"
    if detail:
        line += f" -- {detail}"
    print(line)


def _mask(value: str) -> str:
    if not value:
        return "(empty)"
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}...{value[-2:]} (len {len(value)})"


# ── 1. ENV ───────────────────────────────────────────────────────────
def check_env() -> None:
    print("\n[1] Environment variables")
    required = [
        "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_HOST",
        "POSTGRES_PORT", "POSTGRES_DB", "GROQ_API_KEY", "NEWSAPI_KEY",
    ]
    optional = ["REDIS_URL", "USER_EMAIL"]
    for key in required:
        val = os.getenv(key)
        if val:
            secret = "API" in key or "PASSWORD" in key
            record(OK, key, _mask(val) if secret else val)
        else:
            record(FAIL, key, "missing")
    for key in optional:
        val = os.getenv(key)
        record(OK if val else WARN, key, (val if val else "unset (default used)"))


# ── 2. IMPORTS ───────────────────────────────────────────────────────
def check_imports() -> None:
    print("\n[2] Module imports")
    modules = [
        "backend.db.models",
        "backend.db.crud",
        "backend.db.session",
        "backend.ingestion.pipeline",
        "backend.rag.embedder",
        "backend.rag.retriever",
        "backend.ml.earnings_predictor",
        "backend.ml.anomaly_detector",
        "backend.ml.beneish_score",
        "backend.ml.sentiment_evaluator",
        "backend.ml.peer_clustering",
        "backend.ml.revenue_forecaster",
        "backend.agents.prompts",
        "backend.agents.supervisor",
        "backend.agents.analyzer",
        "backend.agents.synthesizer",
        "backend.agents.run_agent",
        "backend.api.main",
        "backend.api.routes.analysis",
        "backend.tasks.celery_app",
        "backend.tasks.analysis_tasks",
        "backend.evaluation.ragas_eval",
        "scripts.smoke_test",
    ]
    for mod in modules:
        try:
            importlib.import_module(mod)
            record(OK, mod)
        except Exception as e:
            record(FAIL, mod, f"{type(e).__name__}: {e}")


# ── 3. DEPS ──────────────────────────────────────────────────────────
def check_deps() -> None:
    print("\n[3] Optional/auxiliary dependencies")
    # httpx is required by fastapi.testclient (smoke_test stage e).
    try:
        import httpx  # noqa: F401
        record(OK, "httpx", "available (TestClient round-trip will work)")
    except Exception:
        record(
            WARN, "httpx",
            "missing -- smoke_test stage (e) needs it; `uv add --dev httpx`",
        )


# ── 4 & 6. POSTGRES + MIGRATIONS ─────────────────────────────────────
def check_postgres_and_migrations() -> None:
    print("\n[4] PostgreSQL + Alembic")
    try:
        from sqlalchemy import text
        from backend.db.session import engine
    except Exception as e:
        record(FAIL, "db.session import", str(e))
        return

    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        record(OK, "postgres connect", "SELECT 1 ok")
    except Exception as e:
        record(WARN, "postgres connect", f"unreachable ({type(e).__name__}) -- run `docker compose up -d`")
        return

    # pgvector extension present?
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            ).first()
        record(OK if row else WARN, "pgvector extension",
               "installed" if row else "not installed (migrations create it)")
    except Exception as e:
        record(WARN, "pgvector extension", str(e))

    # Alembic: DB revision vs head
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        from alembic.runtime.migration import MigrationContext

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        with engine.connect() as conn:
            current = MigrationContext.configure(conn).get_current_revision()
        if current is None:
            record(WARN, "alembic revision",
                   f"DB unversioned; run `uv run alembic upgrade head` (head={heads[0][:12]})")
        elif current in heads:
            record(OK, "alembic revision", f"at head {current[:12]}")
        else:
            record(WARN, "alembic revision",
                   f"DB at {current[:12]}, head {heads[0][:12]} -- run `uv run alembic upgrade head`")
    except Exception as e:
        record(WARN, "alembic revision", str(e))


def check_migration_chain() -> None:
    print("\n[6] Migration chain")
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory

        cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(cfg)
        heads = script.get_heads()
        if len(heads) == 1:
            record(OK, "single head", heads[0][:12])
        else:
            record(FAIL, "single head", f"{len(heads)} heads (branching): {heads}")
    except Exception as e:
        record(WARN, "migration chain", str(e))


# ── 5. REDIS ─────────────────────────────────────────────────────────
def check_redis() -> None:
    print("\n[5] Redis (Celery broker)")
    url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        import redis

        client = redis.from_url(url, socket_connect_timeout=2)
        client.ping()
        record(OK, "redis ping", url)
    except Exception as e:
        record(WARN, "redis ping", f"unreachable ({type(e).__name__}) -- run `docker compose up -d`")


def main() -> int:
    print("=" * 64)
    print(" financial-research-agent — health check")
    print("=" * 64)

    check_env()
    check_imports()
    check_deps()
    check_postgres_and_migrations()
    check_redis()
    check_migration_chain()

    # Summary
    counts = {OK: 0, WARN: 0, FAIL: 0}
    for status, _, _ in results:
        counts[status] += 1
    print("\n" + "=" * 64)
    print(f" SUMMARY: {counts[OK]} pass, {counts[WARN]} warn, {counts[FAIL]} fail")
    print("=" * 64)
    if critical_failed:
        print(" RESULT: NOT HEALTHY (critical failures above)")
        return 1
    if counts[WARN]:
        print(" RESULT: HEALTHY (code OK; some services/optional items need attention)")
        return 0
    print(" RESULT: FULLY HEALTHY")
    return 0


if __name__ == "__main__":
    sys.exit(main())
