"""
Backtest engine: replays historical reports as signals and computes
forward returns.

For each report in the backtest scope:
  1. Compute signal from report_to_signal.
  2. Look up entry price (close on report.created_at date).
  3. Look up exit prices at +30 and +90 days.
  4. Compute returns and "hit" flag.
Stores per-report results to backtest_results and aggregates a summary
into backtest_runs.summary.

⚠ METHODOLOGY / LIMITATIONS (v1 — read before trusting results):
  - Reports cluster around when batch ingestion was run, not at uniform
    intervals; this biases the sample.
  - No lookahead-bias guard: we assume each report only used data up to
    its created_at. If the synthesizer's context included later data,
    results are misleading.
  - "Signal" is a coarse heuristic (see signals.py), not a real strategy.
  - Forward windows are CALENDAR days (next trading day's close is used
    when markets are closed), not strict trading days.
  - Returns are gross: no transaction costs, slippage, or borrow costs.
  - Per-ticker sample sizes are usually small (<10). Results are
    illustrative, not statistically significant.
"""
from typing import Callable, Optional

import structlog

from backend.backtesting.prices import get_forward_return, get_price_on
from backend.backtesting.signals import report_to_signal
from backend.db.models import BacktestResult, BacktestRun, Company, Report, utcnow
from backend.db.session import SessionLocal

logger = structlog.get_logger(__name__)

ProgressCb = Callable[[dict], None]


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def _summarize(results: list[dict]) -> dict:
    bullish = [r for r in results if r["signal"] == "bullish"]
    bearish = [r for r in results if r["signal"] == "bearish"]
    neutral = [r for r in results if r["signal"] == "neutral"]

    def hit_rate(rows: list[dict]) -> Optional[float]:
        scored = [r for r in rows if r["hit"] is not None]
        return (sum(r["hit"] for r in scored) / len(scored)) if scored else None

    by_ticker: dict[str, dict] = {}
    tickers = {r["ticker"] for r in results}
    for t in tickers:
        rows = [r for r in results if r["ticker"] == t]
        scored = [r for r in rows if r["hit"] is not None]
        by_ticker[t] = {
            "n": len(rows),
            "hit_rate_30d": (sum(r["hit"] for r in scored) / len(scored)) if scored else None,
        }

    return {
        "total_reports": len(results),
        "bullish_count": len(bullish),
        "bearish_count": len(bearish),
        "neutral_count": len(neutral),
        "bullish_hit_rate_30d": hit_rate(bullish),
        "bearish_hit_rate_30d": hit_rate(bearish),
        "avg_return_bullish_30d": _mean([r["return_30d"] for r in bullish if r["return_30d"] is not None]),
        "avg_return_bearish_30d": _mean([r["return_30d"] for r in bearish if r["return_30d"] is not None]),
        "avg_return_bullish_90d": _mean([r["return_90d"] for r in bullish if r["return_90d"] is not None]),
        "avg_return_bearish_90d": _mean([r["return_90d"] for r in bearish if r["return_90d"] is not None]),
        "by_ticker": by_ticker,
    }


def run_backtest(
    name: str,
    ticker_filter: Optional[list[str]] = None,
    min_confidence: float = 0.0,
    progress_cb: Optional[ProgressCb] = None,
) -> int:
    """Run a backtest over historical reports. Returns the backtest_run_id."""
    emit = progress_cb or (lambda _m: None)
    db = SessionLocal()
    run = BacktestRun(
        name=name,
        created_at=utcnow(),
        parameters={
            "ticker_filter": ticker_filter,
            "min_confidence": min_confidence,
        },
        status="running",
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    run_id = run.id

    try:
        q = db.query(Report, Company).join(Company, Report.company_id == Company.id)
        if ticker_filter:
            q = q.filter(Company.ticker.in_([t.upper() for t in ticker_filter]))
        if min_confidence > 0:
            q = q.filter(Report.confidence_score >= min_confidence)
        rows = q.order_by(Report.generated_at.asc()).all()

        total = len(rows)
        logger.info("backtest_start", run_id=run_id, total_reports=total)
        results: list[dict] = []

        for idx, (report, company) in enumerate(rows):
            ticker = company.ticker
            report_date = report.generated_at
            signal = report_to_signal(report)

            entry = get_price_on(ticker, report_date) if report_date else None
            ret_30 = get_forward_return(ticker, report_date, 30) if report_date else None
            ret_90 = get_forward_return(ticker, report_date, 90) if report_date else None
            exit_price_30d = (
                entry * (1 + ret_30) if (entry is not None and ret_30 is not None) else None
            )
            exit_price_90d = (
                entry * (1 + ret_90) if (entry is not None and ret_90 is not None) else None
            )

            hit: Optional[int] = None
            if signal == "bullish" and ret_30 is not None:
                hit = 1 if ret_30 > 0 else 0
            elif signal == "bearish" and ret_30 is not None:
                hit = 1 if ret_30 < 0 else 0

            db.add(BacktestResult(
                backtest_run_id=run_id,
                report_id=report.id,
                ticker=ticker,
                report_date=report_date,
                signal=signal,
                confidence_score=report.confidence_score,
                risk_level=report.risk_level,
                entry_price=entry,
                exit_price_30d=exit_price_30d,
                exit_price_90d=exit_price_90d,
                return_30d=ret_30,
                return_90d=ret_90,
                hit=hit,
            ))
            results.append({
                "ticker": ticker, "signal": signal,
                "return_30d": ret_30, "return_90d": ret_90, "hit": hit,
            })

            emit({
                "stage": "processing",
                "message": f"Processed {idx + 1}/{total} ({ticker})",
                "pct": int((idx + 1) / total * 100) if total else 100,
            })

        db.commit()
        summary = _summarize(results)
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        run.summary = summary
        run.status = "completed"
        db.commit()
        logger.info("backtest_complete", run_id=run_id, total=total)
        return run_id
    except Exception as e:
        logger.error("backtest_failed", run_id=run_id, error=str(e))
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if run:
            run.status = "failed"
            run.error = str(e)
            db.commit()
        raise
    finally:
        db.close()
