"""add_religious_sect_and_payment_failed

Revision ID: f3a8d2c1b6e7
Revises: e2f5a8c9b1d3
Create Date: 2026-04-26 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f3a8d2c1b6e7'
down_revision: Union[str, Sequence[str], None] = 'e2f5a8c9b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Religious sect (مذهب) on the citizen profile. Optional — not
    # every citizen wants to disclose, and existing rows obviously
    # didn't fill it.
    op.add_column('users', sa.Column('religious_sect', sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'religious_sect')
