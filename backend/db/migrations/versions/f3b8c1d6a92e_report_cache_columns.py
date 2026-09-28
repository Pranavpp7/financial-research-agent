"""add cache_key + question to reports for report caching

Revision ID: f3b8c1d6a92e
Revises: e7a2c5d9f1b4
Create Date: 2026-05-22

The composite index is named ix_reports_cache_key_created_at per spec, but
is built on (cache_key, generated_at DESC) because the reports table's
timestamp column is `generated_at` (there is no `created_at`).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f3b8c1d6a92e"
down_revision: Union[str, Sequence[str], None] = "e7a2c5d9f1b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("reports", sa.Column("cache_key", sa.String(length=128), nullable=True))
    op.add_column("reports", sa.Column("question", sa.Text(), nullable=True))
    # Existing rows keep cache_key/question = NULL (backfill is a no-op).
    op.create_index(
        "ix_reports_cache_key_created_at",
        "reports",
        ["cache_key", sa.text("generated_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reports_cache_key_created_at", table_name="reports")
    op.drop_column("reports", "question")
    op.drop_column("reports", "cache_key")
