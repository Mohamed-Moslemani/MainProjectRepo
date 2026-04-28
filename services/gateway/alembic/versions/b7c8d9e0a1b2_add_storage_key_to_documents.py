"""add_storage_key_to_documents

Revision ID: b7c8d9e0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-28 03:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b7c8d9e0a1b2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('documents', sa.Column('storage_key', sa.String(), nullable=True))
    op.create_index('ix_documents_storage_key', 'documents', ['storage_key'])


def downgrade() -> None:
    op.drop_index('ix_documents_storage_key', table_name='documents')
    op.drop_column('documents', 'storage_key')
