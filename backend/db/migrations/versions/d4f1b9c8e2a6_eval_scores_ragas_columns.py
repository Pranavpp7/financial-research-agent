"""add answer_relevancy + context_recall to eval_scores

Revision ID: d4f1b9c8e2a6
Revises: c2d9e4a1b7f3
Create Date: 2026-05-21

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d4f1b9c8e2a6"
down_revision: Union[str, Sequence[str], None] = "c2d9e4a1b7f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """
    Ragas baseline persists answer_relevancy and (when ground truth exists)
    context_recall. faithfulness/relevancy/context_precision already exist.
    """
    op.add_column("eval_scores", sa.Column("answer_relevancy", sa.Float(), nullable=True))
    op.add_column("eval_scores", sa.Column("context_recall", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_scores", "context_recall")
    op.drop_column("eval_scores", "answer_relevancy")
