"""filing_chunks embedding to pgvector

Revision ID: f1c3a5e7b912
Revises: b6f4fc7454f0
Create Date: 2026-05-15

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision: str = "f1c3a5e7b912"
down_revision: Union[str, Sequence[str], None] = "b6f4fc7454f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Enable pgvector and convert filing_chunks.embedding from JSON to Vector(1024)."""
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    # filing_chunks is currently empty (no embeddings produced yet),
    # so a drop + add is safe and avoids needing a JSON->vector cast.
    op.drop_column("filing_chunks", "embedding")
    op.add_column(
        "filing_chunks",
        sa.Column("embedding", Vector(1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("filing_chunks", "embedding")
    op.add_column(
        "filing_chunks",
        sa.Column("embedding", sa.JSON(), nullable=True),
    )
