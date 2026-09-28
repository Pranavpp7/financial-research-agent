"""
Alert engine: detects material changes between consecutive reports
for a ticker and dispatches notifications via email or Slack.

Trigger logic (called after each new report is saved):
  - risk_increased: previous low/medium -> new high (or low -> medium)
  - risk_decreased: previous high -> low/medium (or medium -> low)
  - confidence_dropped_20pct: previous confidence - new > 0.2
  - high_risk_flagged: any new report with risk_level == "high"

All external calls (SMTP, Slack webhook) have timeouts and never raise
out of dispatch_alerts -- alert failures must not break the agent pipeline.
"""
import html
import os
import smtplib
from email.message import EmailMessage
from typing import Optional

import requests
import structlog
from sqlalchemy.orm import Session

from backend.db.models import (
    AlertHistory,
    AlertSubscription,
    Company,
    Report,
    ReportCitation,
    utcnow,
)

logger = structlog.get_logger(__name__)

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}
SLACK_WEBHOOK_PREFIX = "https://hooks.slack.com/"
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")


def detect_triggers(
    prev_report: Optional[Report], new_report: Report
) -> list[str]:
    """Pure function: which trigger names fired for this transition."""
    fired: list[str] = []
    new_risk = (new_report.risk_level or "").lower()

    if new_risk == "high":
        fired.append("high_risk_flagged")

    if prev_report is not None:
        prev_risk = (prev_report.risk_level or "").lower()
        if prev_risk in RISK_ORDER and new_risk in RISK_ORDER:
            if RISK_ORDER[new_risk] > RISK_ORDER[prev_risk]:
                fired.append("risk_increased")
            elif RISK_ORDER[new_risk] < RISK_ORDER[prev_risk]:
                fired.append("risk_decreased")
        if (
            prev_report.confidence_score is not None
            and new_report.confidence_score is not None
            and (prev_report.confidence_score - new_report.confidence_score) > 0.2
        ):
            fired.append("confidence_dropped_20pct")

    # de-dupe, preserve order
    seen: set[str] = set()
    return [t for t in fired if not (t in seen or seen.add(t))]


def _top_findings(db: Session, report_id: int, n: int = 3) -> list[str]:
    rows = (
        db.query(ReportCitation)
        .filter(ReportCitation.report_id == report_id)
        .order_by(ReportCitation.id.asc())
        .limit(n)
        .all()
    )
    return [c.claim_text for c in rows if c.claim_text]


# ── senders ──────────────────────────────────────────────────────────
def send_email(destination: str, subject: str, html_body: str) -> tuple[bool, Optional[str]]:
    host = os.getenv("SMTP_HOST")
    sender = os.getenv("SMTP_FROM")
    if not host or not sender:
        logger.warning("smtp_not_configured")
        return False, "SMTP not configured (SMTP_HOST/SMTP_FROM missing)"

    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = destination
    msg.set_content("This alert requires an HTML-capable email client.")
    msg.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(host, port, timeout=10) as server:
            server.starttls()
            if user and password:
                server.login(user, password)
            server.send_message(msg)
        return True, None
    except Exception as e:
        logger.error("email_send_failed", destination=destination, error=str(e))
        return False, str(e)


def send_slack(webhook_url: str, payload: dict) -> tuple[bool, Optional[str]]:
    try:
        resp = requests.post(webhook_url, json=payload, timeout=5)
        resp.raise_for_status()
        return True, None
    except Exception as e:
        logger.error("slack_send_failed", error=str(e))
        return False, str(e)


# ── templates ────────────────────────────────────────────────────────
_RISK_COLOR = {"low": "#10b981", "medium": "#f59e0b", "high": "#ef4444"}


def build_email(
    ticker: str, prev: Optional[Report], new: Report, triggers: list[str],
    findings: list[str],
) -> tuple[str, str]:
    new_risk = (new.risk_level or "unknown").lower()
    prev_risk = (prev.risk_level or "n/a").lower() if prev else "n/a"
    conf = new.confidence_score if new.confidence_score is not None else 0.0
    # Findings are LLM-generated text — escape before interpolating into HTML.
    findings_html = (
        "".join(f"<li>{html.escape(f)}</li>" for f in findings) or "<li>(none)</li>"
    )
    subject = f"⚠ {ticker}: Risk level changed to {new_risk}"
    html = f"""\
<html><body style="font-family:Inter,system-ui,sans-serif;background:#0a0a0f;color:#f1f5f9;padding:24px">
  <h2 style="margin:0 0 8px">{ticker} risk alert</h2>
  <p style="color:#94a3b8">Triggers: {", ".join(triggers)}</p>
  <p>Risk level:
    <span style="background:#1e1e2e;color:#94a3b8;padding:2px 8px;border-radius:6px">{prev_risk}</span>
    &rarr;
    <span style="background:{_RISK_COLOR.get(new_risk, '#64748b')};color:#0a0a0f;padding:2px 8px;border-radius:6px">{new_risk}</span>
  </p>
  <p>Confidence: {conf:.0%}</p>
  <h3>Key findings</h3>
  <ul>{findings_html}</ul>
  <p><a href="{FRONTEND_URL}/report/{new.id}" style="color:#22d3ee">View full report</a></p>
</body></html>"""
    return subject, html


def build_slack(
    ticker: str, prev: Optional[Report], new: Report, triggers: list[str],
    findings: list[str],
) -> dict:
    new_risk = (new.risk_level or "unknown").lower()
    prev_risk = (prev.risk_level or "n/a").lower() if prev else "n/a"
    findings_text = "\n".join(f"• {f}" for f in findings) or "_(none)_"
    return {
        "blocks": [
            {"type": "header", "text": {"type": "plain_text", "text": f"📊 {ticker} alert"}},
            {"type": "section", "text": {
                "type": "mrkdwn",
                "text": f"*Triggers:* {', '.join(triggers)}\n"
                        f"*Risk:* {prev_risk} → *{new_risk}*",
            }},
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*Key findings*\n{findings_text}"}},
            {"type": "actions", "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View full report"},
                "url": f"{FRONTEND_URL}/report/{new.id}",
            }]},
        ]
    }


# ── dispatch ─────────────────────────────────────────────────────────
def dispatch_alerts(db: Session, new_report: Report) -> list[AlertHistory]:
    """Detect triggers vs the previous report and notify matching subs."""
    company = db.query(Company).filter(Company.id == new_report.company_id).first()
    if not company:
        return []
    ticker = company.ticker

    prev = (
        db.query(Report)
        .filter(Report.company_id == new_report.company_id, Report.id != new_report.id)
        .order_by(Report.generated_at.desc())
        .first()
    )

    fired = detect_triggers(prev, new_report)
    if not fired:
        return []

    subs = (
        db.query(AlertSubscription)
        .filter(AlertSubscription.ticker == ticker, AlertSubscription.active == 1)
        .all()
    )
    if not subs:
        return []

    findings = _top_findings(db, new_report.id, 3)
    history: list[AlertHistory] = []

    for sub in subs:
        matching = sorted(set(sub.triggers or []) & set(fired))
        if not matching:
            continue

        if sub.channel == "email":
            subject, html = build_email(ticker, prev, new_report, matching, findings)
            ok, err = send_email(sub.destination, subject, html)
            payload = {"subject": subject}
        elif sub.channel == "slack":
            blocks = build_slack(ticker, prev, new_report, matching, findings)
            ok, err = send_slack(sub.destination, blocks)
            payload = blocks
        else:
            ok, err = False, f"unknown channel {sub.channel}"
            payload = {}

        row = AlertHistory(
            subscription_id=sub.id,
            fired_at=utcnow(),
            trigger_type=",".join(matching),
            report_id_before=prev.id if prev else None,
            report_id_after=new_report.id,
            payload=payload,
            delivery_status="sent" if ok else "failed",
            delivery_error=err,
        )
        db.add(row)
        sub.last_fired_at = utcnow()
        history.append(row)
        logger.info(
            "alert_dispatched", ticker=ticker, channel=sub.channel,
            triggers=matching, status=row.delivery_status,
        )

    db.commit()
    return history
