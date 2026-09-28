"""Routes: submit analyses, poll status, fetch saved reports, list companies."""
from datetime import datetime, timezone

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException
from sqlalchemy import func

from backend.api.schemas.requests import AnalysisRequest
from backend.api.schemas.responses import (
    ReportHistoryItem,
    ReportResponse,
    TaskResponse,
    TaskStatusResponse,
)
from backend.db.crud import get_company
from backend.db.models import Company, MLPrediction, Report, ReportCitation
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

# Celery reports PENDING both for tasks not-yet-picked-up AND for completely
# unknown task IDs (typo'd or expired past result_expires) -- so a bad id
# would otherwise poll "pending" forever. On submit we drop a short-lived
# marker key; a PENDING task with no marker is treated as unknown/expired.
_TASK_MARKER_PREFIX = "fra:task-known:"
_TASK_MARKER_TTL = int(celery_app.conf.result_expires or 3600)


def _task_backend_redis():
    """Celery's Redis result-backend client, or None if unavailable."""
    try:
        return celery_app.backend.client
    except Exception:
        return None


def _mark_task_submitted(task_id: str) -> None:
    client = _task_backend_redis()
    if client is not None:
        try:
            client.set(f"{_TASK_MARKER_PREFIX}{task_id}", "1", ex=_TASK_MARKER_TTL)
        except Exception:
            pass  # marker is best-effort; never block submission


def _task_is_known(task_id: str) -> bool:
    """True unless we can positively confirm the id was never submitted.
    Fails open (returns True) if Redis is unreachable, so a transient Redis
    blip never mislabels a real in-flight task as unknown."""
    client = _task_backend_redis()
    if client is None:
        return True
    try:
        return bool(client.exists(f"{_TASK_MARKER_PREFIX}{task_id}"))
    except Exception:
        return True


def _latest_shap(db, company_id: int, model_name: str) -> dict | None:
    """Latest shap_values dict for a model, or None. Cold-start sentinel
    rows (status='insufficient_data') are returned as-is — the frontend
    renders them as an explicit "insufficient history" card."""
    pred = (
        db.query(MLPrediction)
        .filter(
            MLPrediction.company_id == company_id,
            MLPrediction.model_name == model_name,
        )
        .order_by(MLPrediction.run_date.desc())
        .first()
    )
    if not pred or not isinstance(pred.shap_values, dict):
        return None
    return pred.shap_values


def _build_report_response(report: Report, company: Company) -> ReportResponse:
    # key_findings live in report_citations (one row per finding), not on
    # the report row itself -- pull them back in insertion order. Forecast +
    # peer signals come from the latest ml_predictions rows for the company.
    db = SessionLocal()
    try:
        findings = [
            c.claim_text
            for c in (
                db.query(ReportCitation)
                .filter(ReportCitation.report_id == report.id)
                .order_by(ReportCitation.id.asc())
                .all()
            )
            if c.claim_text
        ]
        forecast = _latest_shap(db, company.id, "revenue_forecaster")
        peers = _latest_shap(db, company.id, "peer_clustering")
    finally:
        db.close()

    return ReportResponse(
        report_id=report.id,
        ticker=company.ticker,
        company_name=company.name,
        generated_at=report.generated_at,
        bull_case=report.bull_case,
        bear_case=report.bear_case,
        risk_level=report.risk_level,
        confidence_score=report.confidence_score,
        data_quality=report.data_quality,
        analyst_notes=report.analyst_notes,
        key_findings=findings,
        sources=report.sources or [],
        forecast=forecast,
        peers=peers,
    )


@router.post("/analyze", response_model=TaskResponse)
def submit_analysis(request: AnalysisRequest) -> TaskResponse:
    """Queue an analysis. Returns a task_id to poll."""
    task = run_analysis_task.delay(request.ticker, request.question)
    _mark_task_submitted(task.id)
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

    # A bare PENDING with no submission marker means the id was never queued
    # (typo) or its result has expired -- report that instead of "pending".
    if state == "PENDING" and not _task_is_known(task_id):
        raise HTTPException(
            status_code=404,
            detail="unknown or expired task id",
        )

    # Custom PROGRESS state carries {stage, message, pct} in meta.
    if state == "PROGRESS":
        meta = async_result.info if isinstance(async_result.info, dict) else {}
        return TaskStatusResponse(
            task_id=task_id,
            status="progress",
            stage=meta.get("stage"),
            message=meta.get("message"),
            pct=meta.get("pct"),
        )

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


@router.get("/reports/{ticker}", response_model=list[ReportHistoryItem])
def get_report_history(ticker: str) -> list[ReportHistoryItem]:
    """All saved reports for a ticker, newest first (no new analysis)."""
    db = SessionLocal()
    try:
        company = get_company(db, ticker.upper())
        if not company:
            raise HTTPException(status_code=404, detail=f"unknown ticker {ticker}")
        reports = (
            db.query(Report)
            .filter(Report.company_id == company.id)
            .order_by(Report.generated_at.desc())
            .all()
        )
        items: list[ReportHistoryItem] = []
        for r in reports:
            findings = [
                c.claim_text
                for c in (
                    db.query(ReportCitation)
                    .filter(ReportCitation.report_id == r.id)
                    .order_by(ReportCitation.id.asc())
                    .all()
                )
                if c.claim_text
            ]
            items.append(ReportHistoryItem(
                report_id=r.id,
                created_at=r.generated_at,
                risk_level=r.risk_level,
                confidence_score=r.confidence_score,
                bull_case=r.bull_case,
                bear_case=r.bear_case,
                key_findings=findings,
                data_quality=r.data_quality,
                analyst_notes=r.analyst_notes,
            ))
        return items
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
