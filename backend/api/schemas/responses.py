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
    forecast: dict | None = None   # revenue_forecaster shap_values
    peers: dict | None = None      # peer_clustering shap_values


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
