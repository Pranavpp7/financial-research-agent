"""backtest_runs + backtest_results tables

Revision ID: c8e3a1f5d2b9
Revises: b5d2f9a3c7e1
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c8e3a1f5d2b9"
down_revision: Union[str, Sequence[str], None] = "b5d2f9a3c7e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "backtest_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("parameters", sa.JSON(), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_table(
        "backtest_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("backtest_run_id", sa.Integer(),
                  sa.ForeignKey("backtest_runs.id"), nullable=False),
        sa.Column("report_id", sa.Integer(), sa.ForeignKey("reports.id"), nullable=True),
        sa.Column("ticker", sa.String(length=10), nullable=True),
        sa.Column("report_date", sa.DateTime(), nullable=True),
        sa.Column("signal", sa.String(length=10), nullable=True),
        sa.Column("confidence_score", sa.Float(), nullable=True),
        sa.Column("risk_level", sa.String(length=20), nullable=True),
        sa.Column("entry_price", sa.Float(), nullable=True),
        sa.Column("exit_price_30d", sa.Float(), nullable=True),
        sa.Column("exit_price_90d", sa.Float(), nullable=True),
        sa.Column("return_30d", sa.Float(), nullable=True),
        sa.Column("return_90d", sa.Float(), nullable=True),
        sa.Column("hit", sa.Integer(), nullable=True),
    )
    op.create_index("ix_backtest_results_run_id", "backtest_results", ["backtest_run_id"])


def downgrade() -> None:
    op.drop_index("ix_backtest_results_run_id", table_name="backtest_results")
    op.drop_table("backtest_results")
    op.drop_table("backtest_runs")
