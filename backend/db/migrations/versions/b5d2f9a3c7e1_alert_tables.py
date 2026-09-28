"""alert_subscriptions + alert_history tables

Revision ID: b5d2f9a3c7e1
Revises: a1c4e8f2b6d3
Create Date: 2026-05-22

Channel / delivery_status are stored as String columns (with documented
allowed values) rather than Postgres ENUM types, to keep migrations simple
and avoid enum-type alter pain later.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b5d2f9a3c7e1"
down_revision: Union[str, Sequence[str], None] = "a1c4e8f2b6d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "alert_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=True),
        sa.Column("destination", sa.String(length=500), nullable=True),
        sa.Column("triggers", sa.JSON(), nullable=True),
        sa.Column("active", sa.Integer(), server_default="1", nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_fired_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_alert_subscriptions_ticker", "alert_subscriptions", ["ticker"])

    op.create_table(
        "alert_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subscription_id", sa.Integer(),
                  sa.ForeignKey("alert_subscriptions.id"), nullable=False),
        sa.Column("fired_at", sa.DateTime(), nullable=True),
        sa.Column("trigger_type", sa.String(length=50), nullable=True),
        sa.Column("report_id_before", sa.Integer(), sa.ForeignKey("reports.id"), nullable=True),
        sa.Column("report_id_after", sa.Integer(), sa.ForeignKey("reports.id"), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("delivery_status", sa.String(length=20), nullable=True),
        sa.Column("delivery_error", sa.Text(), nullable=True),
    )
    op.create_index("ix_alert_history_subscription_id", "alert_history", ["subscription_id"])


def downgrade() -> None:
    op.drop_index("ix_alert_history_subscription_id", table_name="alert_history")
    op.drop_table("alert_history")
    op.drop_index("ix_alert_subscriptions_ticker", table_name="alert_subscriptions")
    op.drop_table("alert_subscriptions")
