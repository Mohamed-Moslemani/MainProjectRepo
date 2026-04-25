"""add_request_id_to_audit_logs

Revision ID: b8d2c4e5f6a1
Revises: a7c1b3d8e9f4
Create Date: 2026-04-25 01:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b8d2c4e5f6a1'
down_revision: Union[str, Sequence[str], None] = 'a7c1b3d8e9f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('audit_logs', sa.Column('request_id', sa.String(), nullable=True))
    op.create_index(
        'ix_audit_logs_request_id', 'audit_logs', ['request_id'], unique=False
    )


def downgrade() -> None:
    op.drop_index('ix_audit_logs_request_id', table_name='audit_logs')
    op.drop_column('audit_logs', 'request_id')
