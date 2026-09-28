"""Pydantic v2 request schemas."""
from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    ticker: str = Field(..., description="Stock ticker, e.g. 'AAPL'")
    question: str = Field(
        default="Give me a comprehensive analysis",
        description="Free-form research question",
    )


class BatchAnalysisRequest(BaseModel):
    tickers: list[str] = Field(..., description="List of tickers to analyze")
    question: str = Field(..., description="Question to ask for each ticker")
