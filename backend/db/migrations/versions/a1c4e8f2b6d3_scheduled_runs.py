"""scheduled_runs table + watchlist.last_analyzed_at

Revision ID: a1c4e8f2b6d3
Revises: f3b8c1d6a92e
Create Date: 2026-05-22
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c4e8f2b6d3"
down_revision: Union[str, Sequence[str], None] = "f3b8c1d6a92e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("watchlist", sa.Column("last_analyzed_at", sa.DateTime(), nullable=True))
    op.create_table(
        "scheduled_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("task_name", sa.String(length=100), nullable=True),
        sa.Column("ran_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("summary", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_scheduled_runs_task_name", "scheduled_runs", ["task_name"])


def downgrade() -> None:
    op.drop_index("ix_scheduled_runs_task_name", table_name="scheduled_runs")
    op.drop_table("scheduled_runs")
    op.drop_column("watchlist", "last_analyzed_at")
