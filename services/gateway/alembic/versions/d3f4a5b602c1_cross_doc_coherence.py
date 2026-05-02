"""add cross_doc_coherence column to cases

Persists the pair-wise OCR-doc reconciliation result so the audit
trail can show exactly which fields diverged between which documents
when a case is rejected for cross-doc identity mismatch.

Revision ID: d3f4a5b602c1
Revises: c2e3f4a5b601
Create Date: 2026-05-02 21:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd3f4a5b602c1'
down_revision: Union[str, Sequence[str], None] = 'c2e3f4a5b601'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('cross_doc_coherence', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'cross_doc_coherence')
