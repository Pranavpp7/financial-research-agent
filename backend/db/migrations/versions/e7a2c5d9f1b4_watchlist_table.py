"""create watchlist table

Revision ID: e7a2c5d9f1b4
Revises: d4f1b9c8e2a6
Create Date: 2026-05-22

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7a2c5d9f1b4"
down_revision: Union[str, Sequence[str], None] = "d4f1b9c8e2a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "watchlist",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ticker", sa.String(length=10), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("ticker", name="uq_watchlist_ticker"),
    )


def downgrade() -> None:
    op.drop_table("watchlist")
