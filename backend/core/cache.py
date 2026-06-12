"""
Report cache layer.

Given (ticker, question), check whether a sufficiently fresh report
already exists in the `reports` table. If yes, return it; if no, the
caller proceeds with full analysis.

Cache key is a deterministic SHA256 of:
  f"{ticker}|{normalize_question(question)}|{AGENT_VERSION}"

where normalize_question lowercases, strips, and collapses whitespace.
AGENT_VERSION is bumped manually when prompts or agent logic change.
"""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy.orm import Session

from backend.db.models import Report, ReportCitation

logger = structlog.get_logger(__name__)

# Bump on every prompt/agent change so cache invalidates correctly.
AGENT_VERSION = "v1.0"

# Default freshness window (minutes). Read from CACHE_TTL_MINUTES in callers.
DEFAULT_TTL_MINUTES = 360

_WS_RE = re.compile(r"\s+")


def normalize_question(question: Optional[str]) -> str:
    """Lower-case, strip, and collapse whitespace."""
    if not question:
        return ""
    return _WS_RE.sub(" ", question.strip().lower())


def make_cache_key(ticker: str, question: str) -> str:
    """Deterministic SHA256 of (ticker, normalized question, agent version)."""
    raw = f"{ticker.upper()}|{normalize_question(question)}|{AGENT_VERSION}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()  # 64 hex chars


def find_fresh_report(
    db: Session,
    ticker: str,
    question: str,
    max_age_minutes: int = DEFAULT_TTL_MINUTES,
) -> Optional[Report]:
    """
    Most recent report for this (ticker, question) cache key whose
    generated_at is within the freshness window, or None.
    Backed by ix_reports_cache_key_created_at.
    """
    key = make_cache_key(ticker, question)
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    report = (
        db.query(Report)
        .filter(Report.cache_key == key)
        .filter(Report.generated_at >= cutoff)
        .order_by(Report.generated_at.desc())
        .first()
    )
    if report:
        logger.info(
            "cache_lookup_hit", ticker=ticker.upper(),
            report_id=report.id, age_minutes=report.age_minutes,
        )
    return report


def report_to_dict(db: Session, report: Report, from_cache: bool = True) -> dict:
    """
    Serialize a Report row into the same shape `run_agent.analyze` returns,
    so a cache hit is interchangeable with a fresh run downstream.
    """
    key_findings = [
        c.claim_text
        for c in (
            db.query(ReportCitation)
            .filter(ReportCitation.report_id == report.id)
            .order_by(ReportCitation.id.asc())
            .all()
        )
        if c.claim_text
    ]
    return {
        "report_id": report.id,
        "bull_case": report.bull_case,
        "bear_case": report.bear_case,
        "risk_level": report.risk_level,
        "confidence_score": report.confidence_score,
        "data_quality": report.data_quality,
        "analyst_notes": report.analyst_notes,
        "key_findings": key_findings,
        "sources": report.sources or [],
        "from_cache": from_cache,
        "age_minutes": report.age_minutes,
    }
