"""add data_quality + analyst_notes to reports

Revision ID: c2d9e4a1b7f3
Revises: f1c3a5e7b912
Create Date: 2026-05-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2d9e4a1b7f3"
down_revision: Union[str, Sequence[str], None] = "f1c3a5e7b912"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Synthesizer now emits a data-quality score and free-text analyst notes."""
    op.add_column("reports", sa.Column("data_quality", sa.Float(), nullable=True))
    op.add_column("reports", sa.Column("analyst_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("reports", "analyst_notes")
    op.drop_column("reports", "data_quality")
