"""add_model_versions_to_cases

Revision ID: e2f5a8c9b1d3
Revises: d1e2f3a4b5c6
Create Date: 2026-04-26 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e2f5a8c9b1d3'
down_revision: Union[str, Sequence[str], None] = 'd1e2f3a4b5c6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('model_versions', sa.JSON(), nullable=True))
    op.add_column('ocr_results', sa.Column('input_hash', sa.String(), nullable=True))
    op.create_index('ix_ocr_results_input_hash', 'ocr_results', ['input_hash'])


def downgrade() -> None:
    op.drop_index('ix_ocr_results_input_hash', table_name='ocr_results')
    op.drop_column('ocr_results', 'input_hash')
    op.drop_column('cases', 'model_versions')
