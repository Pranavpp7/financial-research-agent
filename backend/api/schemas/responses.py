"""Pydantic v2 response schemas."""
from datetime import datetime

from pydantic import BaseModel, Field


class TaskResponse(BaseModel):
    task_id: str
    status: str = Field(..., description="pending | running | completed | failed")
    message: str


class ReportResponse(BaseModel):
    ticker: str
    company_name: str | None = None
    generated_at: datetime | None = None
    bull_case: str | None = None
    bear_case: str | None = None
    risk_level: str | None = None
    confidence_score: float | None = None
    sources: list | None = None


class TaskStatusResponse(BaseModel):
    task_id: str
    status: str = Field(..., description="pending | running | completed | failed")
    result: ReportResponse | None = None
    error: str | None = None
