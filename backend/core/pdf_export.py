"""
PDF report generator using WeasyPrint.

Renders an HTML template (Jinja2) with the report data, then WeasyPrint
converts it to a styled PDF. Templates live in backend/templates/.

WeasyPrint is imported lazily inside render_report_pdf because it loads
native cairo/pango libraries at import time; deferring keeps this module
importable on machines without those system libs (Windows dev, CI).
"""
import html
import re
from pathlib import Path
from typing import Optional

import structlog
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.db.models import Company, MLPrediction, Report

logger = structlog.get_logger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html"]),
)

_SOURCE_TAG_RE = re.compile(r"\(source:[^)]*\)", re.IGNORECASE)


def _highlight_source_tags(text: Optional[str]) -> str:
    """Escape text, then wrap inline (source: ...) tags in a styled span."""
    if not text:
        return ""
    escaped = html.escape(text)
    return _SOURCE_TAG_RE.sub(
        lambda m: f'<span class="src">{m.group(0)[1:-1]}</span>', escaped
    )


def _ml_signals(ml_predictions: list[MLPrediction]) -> list[tuple[str, str]]:
    """Flatten the latest ML predictions into (label, value) rows."""
    rows: list[tuple[str, str]] = []
    latest: dict[str, MLPrediction] = {}
    for p in ml_predictions:
        if p.model_name not in latest:
            latest[p.model_name] = p
    for name, p in latest.items():
        rows.append((name, f"pred={p.prediction}  conf={p.confidence}"))
    return rows


def render_report_pdf(
    report: Report,
    company: Company,
    ml_predictions: list[MLPrediction],
) -> bytes:
    """Render a report to PDF bytes. Raises if WeasyPrint/native libs missing."""
    from weasyprint import HTML  # lazy import (native libs)

    key_findings = [c.claim_text for c in report.citations if c.claim_text]

    context = {
        "ticker": company.ticker,
        "company_name": company.name or company.ticker,
        "generated_at": (
            report.generated_at.strftime("%Y-%m-%d %H:%M UTC")
            if report.generated_at else "—"
        ),
        "risk_level": (report.risk_level or "low").lower(),
        "confidence_pct": round((report.confidence_score or 0.0) * 100),
        "data_quality_pct": round((report.data_quality or 0.0) * 100),
        "bull_case_html": _highlight_source_tags(report.bull_case),
        "bear_case_html": _highlight_source_tags(report.bear_case),
        "key_findings": key_findings,
        "analyst_notes": report.analyst_notes or "",
        "ml_signals": _ml_signals(ml_predictions),
        "sources": [
            s if isinstance(s, str) else str(s) for s in (report.sources or [])
        ],
    }

    html_str = _env.get_template("report.html").render(**context)
    pdf_bytes = HTML(string=html_str).write_pdf()
    logger.info("pdf_rendered", report_id=report.id, bytes=len(pdf_bytes))
    return pdf_bytes
