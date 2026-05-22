"""
End-to-end smoke test for the financial-research-agent pipeline.

Runs every stage for one ticker (default AAPL) and asserts each succeeds:

  a) Ingestion  -> earnings + filings rows written
  b) Embedding  -> at least one filing_chunks row for the ticker
  c) ML models  -> earnings / anomaly / beneish / sentiment each write a
                   fresh ml_predictions row
  d) Agent      -> analyze() returns a populated report
  e) API        -> POST /analyze then poll GET /analyze/{task_id} to completion

This is an integration test: it needs Postgres up, a GROQ_API_KEY, and
network access to EDGAR / yfinance / NewsAPI. Stage (e) runs Celery in
eager (in-process) mode with an in-memory result backend, so it does NOT
need a separate Redis broker or Celery worker running.

Usage:
  uv run --module scripts.smoke_test               # AAPL
  uv run --module scripts.smoke_test --ticker NVDA
  uv run python scripts/smoke_test.py --ticker AAPL
"""
import argparse
import os
import sys
import time
from pathlib import Path

# Allow `python scripts/smoke_test.py` as well as `-m scripts.smoke_test`
# by ensuring the repo root (parent of scripts/) is importable.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from dotenv import load_dotenv

load_dotenv()


class SmokeError(AssertionError):
    """Raised when a smoke-test stage fails its assertions."""


def _hr(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def _require_env(*names: str) -> None:
    missing = [n for n in names if not os.getenv(n)]
    if missing:
        raise SmokeError(
            f"missing required env var(s): {', '.join(missing)} "
            "(check your .env)"
        )


def _company_id(ticker: str) -> int:
    """Resolve a ticker to its company_id, or raise if not ingested."""
    from backend.db.models import Company
    from backend.db.session import SessionLocal

    db = SessionLocal()
    try:
        company = db.query(Company).filter(Company.ticker == ticker).first()
        if not company:
            raise SmokeError(f"{ticker} not found in companies table")
        return company.id
    finally:
        db.close()


# ── a) INGESTION ────────────────────────────────────────────────────
def stage_ingestion(ticker: str) -> None:
    _hr(f"STAGE A — Ingestion ({ticker})")
    from backend.ingestion.pipeline import run_ingestion_pipeline

    result = run_ingestion_pipeline(ticker)
    if result.get("errors"):
        raise SmokeError(f"ingestion reported errors: {result['errors']}")
    if not result.get("earnings_saved", 0) > 0:
        raise SmokeError(
            f"expected earnings_saved > 0, got {result.get('earnings_saved')}"
        )
    if not result.get("filings_saved", 0) > 0:
        raise SmokeError(
            f"expected filings_saved > 0, got {result.get('filings_saved')}"
        )
    print(
        f"PASS — earnings_saved={result['earnings_saved']} "
        f"filings_saved={result['filings_saved']} "
        f"articles_saved={result.get('articles_saved')}"
    )


# ── b) EMBEDDING ────────────────────────────────────────────────────
def stage_embedding(ticker: str) -> None:
    _hr(f"STAGE B — Embedding ({ticker})")
    from backend.db.models import Company, Filing, FilingChunk
    from backend.db.session import SessionLocal
    from backend.rag import embedder as rag_embedder
    from backend.rag import fetch as rag_fetch

    # The ingestion pipeline saves filing metadata with empty raw_text;
    # fetch.main pulls the most-recent filing's HTML into raw_text so the
    # embedder has something to chunk.
    rag_fetch.main(ticker)
    rag_embedder.run_for_unembedded()

    db = SessionLocal()
    try:
        chunk_count = (
            db.query(FilingChunk)
            .join(Filing, FilingChunk.filing_id == Filing.id)
            .join(Company, Filing.company_id == Company.id)
            .filter(Company.ticker == ticker)
            .count()
        )
    finally:
        db.close()

    if chunk_count <= 0:
        raise SmokeError(
            f"expected >= 1 filing_chunks row for {ticker}, got {chunk_count}"
        )
    print(f"PASS — {chunk_count} filing_chunks rows for {ticker}")


# ── c) ML MODELS ────────────────────────────────────────────────────
def _latest_prediction_count(company_id: int, model_name: str) -> int:
    from backend.db.models import MLPrediction
    from backend.db.session import SessionLocal

    db = SessionLocal()
    try:
        return (
            db.query(MLPrediction)
            .filter(
                MLPrediction.company_id == company_id,
                MLPrediction.model_name == model_name,
            )
            .count()
        )
    finally:
        db.close()


def stage_ml_models(ticker: str) -> None:
    _hr(f"STAGE C — ML models ({ticker})")
    from backend.ml import (
        anomaly_detector,
        beneish_score,
        earnings_predictor,
        sentiment_evaluator,
    )

    company_id = _company_id(ticker)

    # (module, model_name written to ml_predictions)
    models = [
        (earnings_predictor, "earnings_surprise_predictor"),
        (anomaly_detector, "anomaly_detector"),
        (beneish_score, "beneish_m_score"),
        (sentiment_evaluator, "finbert_sentiment"),
    ]

    failures = []
    for module, model_name in models:
        before = _latest_prediction_count(company_id, model_name)
        print(f"\n--- running {module.__name__} ---")
        module.main()
        after = _latest_prediction_count(company_id, model_name)
        if after > before:
            print(f"PASS — {model_name}: wrote a new ml_predictions row")
        else:
            # Several models (anomaly, beneish, earnings) need MORE than one
            # ticker's history to produce output. Surface that clearly.
            failures.append(model_name)
            print(
                f"FAIL — {model_name}: no new ml_predictions row for {ticker} "
                f"(count {before} -> {after}). This model likely needs more "
                "tickers ingested; try run_batch_ingestion first."
            )

    if failures:
        raise SmokeError(
            f"ML models produced no prediction for {ticker}: {failures}"
        )


# ── d) AGENT ────────────────────────────────────────────────────────
def stage_agent(ticker: str) -> dict:
    _hr(f"STAGE D — Agent ({ticker})")
    _require_env("GROQ_API_KEY")
    from backend.agents.run_agent import analyze

    report = analyze(ticker, "Give me a comprehensive analysis of the stock")
    if "error" in report:
        raise SmokeError(f"agent returned error: {report['error']}")

    if not (report.get("bull_case") or "").strip():
        raise SmokeError("bull_case is empty")
    if not (report.get("bear_case") or "").strip():
        raise SmokeError("bear_case is empty")
    if not (report.get("risk_level") or "").strip():
        raise SmokeError("risk_level is empty")
    if not (report.get("confidence_score") or 0) > 0:
        raise SmokeError(
            f"expected confidence_score > 0, got {report.get('confidence_score')}"
        )

    print(
        f"PASS — risk_level={report['risk_level']} "
        f"confidence={report['confidence_score']:.2f} "
        f"data_quality={report.get('data_quality')}"
    )
    return report


# ── e) API ROUND-TRIP ───────────────────────────────────────────────
def stage_api(ticker: str, timeout_s: int = 60) -> None:
    _hr(f"STAGE E — API round-trip ({ticker})")
    _require_env("GROQ_API_KEY")

    # Configure Celery to run tasks in-process so this stage needs no
    # separate Redis broker or worker. Must happen before the app imports.
    from backend.tasks.celery_app import celery_app

    celery_app.conf.task_always_eager = True
    celery_app.conf.task_eager_propagates = True
    celery_app.conf.task_store_eager_result = True
    # In-memory backend so AsyncResult(task_id) resolves without Redis.
    celery_app.conf.result_backend = "cache+memory://"

    from fastapi.testclient import TestClient

    from backend.api.main import app

    client = TestClient(app)

    submit = client.post(
        "/analyze",
        json={"ticker": ticker, "question": "Give me a comprehensive analysis"},
    )
    if submit.status_code != 200:
        raise SmokeError(f"POST /analyze -> {submit.status_code}: {submit.text}")
    task_id = submit.json()["task_id"]
    print(f"  submitted task_id={task_id}")

    deadline = time.time() + timeout_s
    status = None
    payload = {}
    while time.time() < deadline:
        poll = client.get(f"/analyze/{task_id}")
        if poll.status_code != 200:
            raise SmokeError(
                f"GET /analyze/{task_id} -> {poll.status_code}: {poll.text}"
            )
        payload = poll.json()
        status = payload.get("status")
        if status in ("completed", "failed"):
            break
        time.sleep(1)

    if status != "completed":
        raise SmokeError(
            f"task did not complete within {timeout_s}s "
            f"(last status={status}, error={payload.get('error')})"
        )

    result = payload.get("result") or {}
    if not (result.get("bull_case") or "").strip():
        raise SmokeError("API result.bull_case is empty")
    print(
        f"PASS — status=completed, "
        f"risk_level={result.get('risk_level')} "
        f"confidence={result.get('confidence_score')}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="End-to-end pipeline smoke test")
    parser.add_argument("--ticker", default="AAPL", help="ticker to test (default AAPL)")
    parser.add_argument(
        "--skip", default="", help="comma-separated stages to skip: a,b,c,d,e"
    )
    parser.add_argument(
        "--api-timeout", type=int, default=60, help="stage E poll timeout (s)"
    )
    args = parser.parse_args()

    ticker = args.ticker.upper()
    skip = {s.strip().lower() for s in args.skip.split(",") if s.strip()}

    _require_env("POSTGRES_USER", "POSTGRES_DB")

    stages = [
        ("a", lambda: stage_ingestion(ticker)),
        ("b", lambda: stage_embedding(ticker)),
        ("c", lambda: stage_ml_models(ticker)),
        ("d", lambda: stage_agent(ticker)),
        ("e", lambda: stage_api(ticker, args.api_timeout)),
    ]

    results = {}
    for key, fn in stages:
        if key in skip:
            results[key] = "SKIP"
            continue
        try:
            fn()
            results[key] = "PASS"
        except Exception as e:
            results[key] = f"FAIL: {e}"
            print(f"\n!! STAGE {key.upper()} FAILED: {e}")
            break  # stages are ordered dependencies; stop at first failure

    _hr("SMOKE TEST SUMMARY")
    labels = {"a": "ingestion", "b": "embedding", "c": "ml_models",
              "d": "agent", "e": "api"}
    for key in ("a", "b", "c", "d", "e"):
        print(f"  {key}) {labels[key]:12s} {results.get(key, 'NOT RUN')}")

    failed = any(v.startswith("FAIL") for v in results.values())
    print(f"\n{'OVERALL: FAILED' if failed else 'OVERALL: PASSED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
