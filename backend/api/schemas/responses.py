"""Pydantic v2 response schemas."""
from datetime import datetime

from pydantic import BaseModel, Field


class TaskResponse(BaseModel):
    task_id: str
    status: str = Field(..., description="pending | running | completed | failed")
    message: str


class ReportResponse(BaseModel):
    report_id: int | None = None
    ticker: str
    company_name: str | None = None
    generated_at: datetime | None = None
    bull_case: str | None = None
    bear_case: str | None = None
    risk_level: str | None = None
    confidence_score: float | None = None
    data_quality: float | None = None
    analyst_notes: str | None = None
    key_findings: list | None = None
    sources: list | None = None
    forecast: dict | None = None   # normalized revenue_forecaster payload
    peers: dict | None = None      # normalized peer_clustering payload
    # Structured badge inputs from latest ml_predictions (no LLM text).
    # Keys: anomaly, beneish, earnings, sentiment — each a dict or null.
    ml_signals: dict | None = None
    from_cache: bool | None = None  # True if served from the report cache
    age_minutes: int | None = None  # report age when served from cache


class ReportHistoryItem(BaseModel):
    report_id: int
    created_at: datetime | None = None
    risk_level: str | None = None
    confidence_score: float | None = None
    bull_case: str | None = None
    bear_case: str | None = None
    key_findings: list | None = None
    data_quality: float | None = None
    analyst_notes: str | None = None


class WatchlistItem(BaseModel):
    ticker: str
    notes: str | None = None
    created_at: datetime | None = None


class WatchlistSummaryItem(BaseModel):
    ticker: str
    notes: str | None = None
    risk_level: str | None = None
    confidence_score: float | None = None
    last_analyzed: datetime | None = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str = Field(
        ..., description="pending | running | progress | completed | failed"
    )
    result: ReportResponse | None = None
    error: str | None = None
    # Populated when status == "progress".
    stage: str | None = None
    message: str | None = None
    pct: int | None = None
    # Populated when error == "rate_limit_exceeded".
    service: str | None = None
    retry_after_seconds: int | None = None
