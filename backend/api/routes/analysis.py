"""Routes: submit analyses, poll status, fetch saved reports, list companies."""
from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from backend.api.schemas.requests import AnalysisRequest
from backend.api.schemas.responses import (
    ReportResponse,
    TaskResponse,
    TaskStatusResponse,
)
from backend.db.crud import get_company, get_latest_report
from backend.db.models import Company, MLPrediction, Report
from backend.db.session import SessionLocal
from backend.tasks.analysis_tasks import run_analysis_task
from backend.tasks.celery_app import celery_app

router = APIRouter()


# Map Celery internal states to the API's external vocabulary.
_STATE_MAP = {
    "PENDING": "pending",
    "RECEIVED": "pending",
    "STARTED": "running",
    "RETRY": "running",
    "SUCCESS": "completed",
    "FAILURE": "failed",
    "REVOKED": "failed",
}


def _build_report_response(report: Report, company: Company) -> ReportResponse:
    return ReportResponse(
        ticker=company.ticker,
        company_name=company.name,
        generated_at=report.generated_at,
        bull_case=report.bull_case,
        bear_case=report.bear_case,
        risk_level=report.risk_level,
        confidence_score=report.confidence_score,
        sources=report.sources or [],
    )


@router.post("/analyze", response_model=TaskResponse)
def submit_analysis(request: AnalysisRequest) -> TaskResponse:
    """Queue an analysis. Returns a task_id to poll."""
    task = run_analysis_task.delay(request.ticker, request.question)
    return TaskResponse(
        task_id=task.id,
        status="pending",
        message=f"Analysis queued for {request.ticker.upper()}",
    )


@router.get("/analyze/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str) -> TaskStatusResponse:
    """Poll a task. When complete, returns the rendered ReportResponse."""
    async_result = AsyncResult(task_id, app=celery_app)
    state = async_result.state
    status = _STATE_MAP.get(state, state.lower())

    if state == "FAILURE":
        return TaskStatusResponse(
            task_id=task_id,
            status="failed",
            error=str(async_result.result) if async_result.result else "task failed",
        )

    if state != "SUCCESS":
        return TaskStatusResponse(task_id=task_id, status=status)

    task_payload = async_result.result or {}
    if "error" in task_payload:
        return TaskStatusResponse(
            task_id=task_id, status="failed", error=task_payload["error"],
        )

    # Build ReportResponse from the saved row (richer than the task dict).
    report_id = task_payload.get("report_id")
    report_resp = None
    if report_id:
        db = SessionLocal()
        try:
            report = db.query(Report).filter(Report.id == report_id).first()
            if report:
                company = (
                    db.query(Company)
                    .filter(Company.id == report.company_id)
                    .first()
                )
                if company:
                    report_resp = _build_report_response(report, company)
        finally:
            db.close()

    return TaskStatusResponse(task_id=task_id, status=status, result=report_resp)


@router.get("/reports/{ticker}", response_model=ReportResponse)
def get_latest_report_for(ticker: str) -> ReportResponse:
    """Latest saved report for a ticker (does not trigger a new analysis)."""
    db = SessionLocal()
    try:
        company = get_company(db, ticker.upper())
        if not company:
            raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
        report = get_latest_report(db, company.id)
        if not report:
            raise HTTPException(
                status_code=404, detail=f"no report for {ticker} -- run /analyze first",
            )
        return _build_report_response(report, company)
    finally:
        db.close()


@router.get("/companies")
def list_companies():
    """All companies tracked in the database."""
    db = SessionLocal()
    try:
        companies = db.query(Company).order_by(Company.ticker).all()
        return [
            {
                "ticker": c.ticker,
                "name": c.name,
                "sector": c.sector,
                "industry": c.industry,
            }
            for c in companies
        ]
    finally:
        db.close()


@router.get("/stats")
def get_stats():
    """
    Dashboard summary stats: total companies, avg sentiment across the latest
    finbert prediction per company, reports created today (UTC), and a fixed
    count of ML models that exist in this project.
    """
    from datetime import datetime, timezone

    db = SessionLocal()
    try:
        total_companies = db.query(func.count(Company.id)).scalar() or 0

        # Latest finbert_sentiment per company, then average
        latest = (
            db.query(
                MLPrediction.company_id,
                func.max(MLPrediction.run_date).label("max_date"),
            )
            .filter(MLPrediction.model_name == "finbert_sentiment")
            .group_by(MLPrediction.company_id)
            .subquery()
        )
        avg_sentiment = (
            db.query(func.avg(MLPrediction.prediction))
            .join(
                latest,
                (MLPrediction.company_id == latest.c.company_id)
                & (MLPrediction.run_date == latest.c.max_date),
            )
            .filter(MLPrediction.model_name == "finbert_sentiment")
            .scalar()
        )

        today_utc = datetime.now(timezone.utc).date()
        reports_today = (
            db.query(func.count(Report.id))
            .filter(func.date(Report.generated_at) == today_utc)
            .scalar()
            or 0
        )

        return {
            "total_companies": int(total_companies),
            "average_sentiment": (
                float(avg_sentiment) if avg_sentiment is not None else None
            ),
            "reports_today": int(reports_today),
            # 6 ML models: earnings_surprise, anomaly, beneish, peer_clustering,
            # revenue_forecaster, finbert_sentiment
            "models_running": 6,
        }
    finally:
        db.close()


@router.get("/sentiments")
def list_sentiments():
    """
    Latest FinBERT sentiment per company (one row per ticker), for the
    dashboard chart. Reads ml_predictions where model_name='finbert_sentiment'.
    """
    db = SessionLocal()
    try:
        latest = (
            db.query(
                MLPrediction.company_id,
                func.max(MLPrediction.run_date).label("max_date"),
            )
            .filter(MLPrediction.model_name == "finbert_sentiment")
            .group_by(MLPrediction.company_id)
            .subquery()
        )
        rows = (
            db.query(MLPrediction, Company)
            .join(Company, MLPrediction.company_id == Company.id)
            .join(
                latest,
                (MLPrediction.company_id == latest.c.company_id)
                & (MLPrediction.run_date == latest.c.max_date),
            )
            .filter(MLPrediction.model_name == "finbert_sentiment")
            .all()
        )
        return [
            {
                "ticker": company.ticker,
                "name": company.name,
                "sentiment_score": pred.prediction,
                "label": (
                    "positive" if (pred.prediction or 0) > 0.05
                    else "negative" if (pred.prediction or 0) < -0.05
                    else "neutral"
                ),
            }
            for pred, company in rows
        ]
    finally:
        db.close()
