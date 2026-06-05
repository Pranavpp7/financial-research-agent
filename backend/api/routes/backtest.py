"""
Backtest routes.

  POST /backtest                  -> queue a backtest, returns task_id
  GET  /backtest                  -> list all runs (brief)
  GET  /backtest/{run_id}          -> full run with summary
  GET  /backtest/{run_id}/results -> paginated per-report results
"""
import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.db.models import BacktestResult, BacktestRun
from backend.db.session import SessionLocal
from backend.tasks.backtest_tasks import run_backtest_task

router = APIRouter()
logger = structlog.get_logger(__name__)


class BacktestRequest(BaseModel):
    name: str = Field(..., description="Human-readable name for this run")
    tickers: list[str] | None = Field(default=None, description="Subset of tickers, or all")
    min_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


@router.post("/backtest")
def create_backtest(req: BacktestRequest) -> dict:
    task = run_backtest_task.delay(req.name, req.tickers, req.min_confidence)
    return {"task_id": task.id, "status": "queued"}


@router.get("/backtest")
def list_backtests() -> list[dict]:
    db = SessionLocal()
    try:
        runs = db.query(BacktestRun).order_by(BacktestRun.created_at.desc()).all()
        out = []
        for r in runs:
            summary = r.summary if isinstance(r.summary, dict) else {}
            out.append({
                "id": r.id,
                "name": r.name,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "status": r.status,
                "summary_brief": {
                    "total_reports": summary.get("total_reports"),
                    "bullish_hit_rate_30d": summary.get("bullish_hit_rate_30d"),
                    "bearish_hit_rate_30d": summary.get("bearish_hit_rate_30d"),
                },
            })
        return out
    finally:
        db.close()


@router.get("/backtest/{run_id}")
def get_backtest(run_id: int) -> dict:
    db = SessionLocal()
    try:
        run = db.query(BacktestRun).filter(BacktestRun.id == run_id).first()
        if not run:
            raise HTTPException(404, "backtest run not found")
        return {
            "id": run.id,
            "name": run.name,
            "created_at": run.created_at.isoformat() if run.created_at else None,
            "status": run.status,
            "parameters": run.parameters,
            "summary": run.summary,
            "error": run.error,
        }
    finally:
        db.close()


@router.get("/backtest/{run_id}/results")
def get_backtest_results(run_id: int, limit: int = 100, offset: int = 0) -> list[dict]:
    limit = max(1, min(limit, 500))
    db = SessionLocal()
    try:
        rows = (
            db.query(BacktestResult)
            .filter(BacktestResult.backtest_run_id == run_id)
            .order_by(BacktestResult.report_date.asc())
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            {
                "report_id": r.report_id,
                "ticker": r.ticker,
                "report_date": r.report_date.isoformat() if r.report_date else None,
                "signal": r.signal,
                "confidence_score": r.confidence_score,
                "risk_level": r.risk_level,
                "entry_price": r.entry_price,
                "return_30d": r.return_30d,
                "return_90d": r.return_90d,
                "hit": r.hit,
            }
            for r in rows
        ]
    finally:
        db.close()
