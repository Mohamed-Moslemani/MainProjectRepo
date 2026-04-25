"""add_retake_reasons_to_cases

Revision ID: a7c1b3d8e9f4
Revises: 33f99e253445
Create Date: 2026-04-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7c1b3d8e9f4'
down_revision: Union[str, Sequence[str], None] = '33f99e253445'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cases', sa.Column('retake_reasons', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('cases', 'retake_reasons')
