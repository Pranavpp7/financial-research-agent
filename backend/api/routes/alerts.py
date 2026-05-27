"""
Alert subscription + history routes.

  POST   /alerts/subscribe             -> create a subscription
  GET    /alerts/subscriptions?ticker= -> list active subscriptions
  DELETE /alerts/subscriptions/{id}     -> deactivate/remove
  GET    /alerts/history?ticker=&limit= -> paginated alert history
  POST   /alerts/test/{subscription_id} -> send a test alert
"""
import re
import types
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.alerts import (
    SLACK_WEBHOOK_PREFIX,
    build_email,
    build_slack,
    send_email,
    send_slack,
)
from backend.db.models import AlertHistory, AlertSubscription
from backend.db.session import SessionLocal

router = APIRouter()
logger = structlog.get_logger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
VALID_CHANNELS = {"email", "slack"}
VALID_TRIGGERS = {
    "risk_increased", "risk_decreased",
    "confidence_dropped_20pct", "high_risk_flagged",
}


class SubscribeRequest(BaseModel):
    ticker: str = Field(..., description="Ticker to watch")
    channel: str = Field(..., description="'email' or 'slack'")
    destination: str = Field(..., description="email address or Slack webhook URL")
    triggers: list[str] = Field(..., description="trigger types to fire on")


def _validate(channel: str, destination: str, triggers: list[str]) -> None:
    if channel not in VALID_CHANNELS:
        raise HTTPException(400, f"channel must be one of {sorted(VALID_CHANNELS)}")
    if channel == "email" and not _EMAIL_RE.match(destination):
        raise HTTPException(400, "invalid email address")
    if channel == "slack" and not destination.startswith(SLACK_WEBHOOK_PREFIX):
        raise HTTPException(400, f"Slack webhook must start with {SLACK_WEBHOOK_PREFIX}")
    bad = set(triggers) - VALID_TRIGGERS
    if bad:
        raise HTTPException(400, f"invalid triggers: {sorted(bad)}")
    if not triggers:
        raise HTTPException(400, "at least one trigger required")


@router.post("/alerts/subscribe")
def subscribe(req: SubscribeRequest) -> dict:
    _validate(req.channel, req.destination, req.triggers)
    db = SessionLocal()
    try:
        sub = AlertSubscription(
            ticker=req.ticker.upper(),
            channel=req.channel,
            destination=req.destination,
            triggers=req.triggers,
            active=1,
            created_at=datetime.now(timezone.utc),
        )
        db.add(sub)
        db.commit()
        db.refresh(sub)
        logger.info("alert_subscribed", ticker=sub.ticker, channel=sub.channel)
        return {"subscription_id": sub.id}
    finally:
        db.close()


@router.get("/alerts/subscriptions")
def list_subscriptions(ticker: str | None = None) -> list[dict]:
    db = SessionLocal()
    try:
        q = db.query(AlertSubscription).filter(AlertSubscription.active == 1)
        if ticker:
            q = q.filter(AlertSubscription.ticker == ticker.upper())
        return [
            {
                "id": s.id, "ticker": s.ticker, "channel": s.channel,
                "destination": s.destination, "triggers": s.triggers or [],
                "last_fired_at": s.last_fired_at.isoformat() if s.last_fired_at else None,
            }
            for s in q.order_by(AlertSubscription.created_at.desc()).all()
        ]
    finally:
        db.close()


@router.delete("/alerts/subscriptions/{subscription_id}")
def delete_subscription(subscription_id: int) -> dict:
    db = SessionLocal()
    try:
        sub = db.query(AlertSubscription).filter(AlertSubscription.id == subscription_id).first()
        if not sub:
            raise HTTPException(404, "subscription not found")
        db.delete(sub)
        db.commit()
        return {"deleted": subscription_id}
    finally:
        db.close()


@router.get("/alerts/history")
def alert_history(ticker: str | None = None, limit: int = 50) -> list[dict]:
    limit = max(1, min(limit, 200))
    db = SessionLocal()
    try:
        q = db.query(AlertHistory).join(
            AlertSubscription, AlertHistory.subscription_id == AlertSubscription.id
        )
        if ticker:
            q = q.filter(AlertSubscription.ticker == ticker.upper())
        rows = q.order_by(AlertHistory.fired_at.desc()).limit(limit).all()
        return [
            {
                "id": h.id, "subscription_id": h.subscription_id,
                "fired_at": h.fired_at.isoformat() if h.fired_at else None,
                "trigger_type": h.trigger_type,
                "report_id_before": h.report_id_before,
                "report_id_after": h.report_id_after,
                "delivery_status": h.delivery_status,
                "delivery_error": h.delivery_error,
            }
            for h in rows
        ]
    finally:
        db.close()


@router.post("/alerts/test/{subscription_id}")
def test_alert(subscription_id: int) -> dict:
    """Send a test alert with fake data so users can verify channel setup."""
    db = SessionLocal()
    try:
        sub = db.query(AlertSubscription).filter(AlertSubscription.id == subscription_id).first()
        if not sub:
            raise HTTPException(404, "subscription not found")

        # Fake prev/new reports (not persisted) for template rendering.
        fake_new = types.SimpleNamespace(id=0, risk_level="high", confidence_score=0.45)
        fake_prev = types.SimpleNamespace(id=0, risk_level="low", confidence_score=0.85)
        findings = ["This is a TEST alert.", "Channel configuration check.", "No action needed."]
        triggers = ["risk_increased", "high_risk_flagged"]

        if sub.channel == "email":
            subject, html = build_email(sub.ticker, fake_prev, fake_new, triggers, findings)
            ok, err = send_email(sub.destination, "[TEST] " + subject, html)
        elif sub.channel == "slack":
            blocks = build_slack(sub.ticker, fake_prev, fake_new, triggers, findings)
            ok, err = send_slack(sub.destination, blocks)
        else:
            ok, err = False, f"unknown channel {sub.channel}"

        db.add(AlertHistory(
            subscription_id=sub.id,
            fired_at=datetime.now(timezone.utc),
            trigger_type="test",
            report_id_before=None,
            report_id_after=None,
            payload={"test": True},
            delivery_status="sent" if ok else "failed",
            delivery_error=err,
        ))
        db.commit()
        return {"sent": ok, "error": err}
    finally:
        db.close()
