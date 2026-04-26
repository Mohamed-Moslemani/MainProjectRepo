"""add_idempotency_and_stripe_events

Revision ID: c9f3a4d7e2b8
Revises: b8d2c4e5f6a1
Create Date: 2026-04-26 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'c9f3a4d7e2b8'
down_revision: Union[str, Sequence[str], None] = 'b8d2c4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'stripe_events',
        sa.Column('event_id', sa.String(), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=True),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('event_id'),
    )
    op.create_index('ix_stripe_events_event_type', 'stripe_events', ['event_type'])
    op.create_index('ix_stripe_events_case_id', 'stripe_events', ['case_id'])
    op.create_index('ix_stripe_events_received_at', 'stripe_events', ['received_at'])

    op.create_table(
        'idempotency_keys',
        sa.Column('user_id', sa.String(), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('route', sa.String(), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=False, server_default='200'),
        sa.Column('response_json', sa.JSON(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'key', 'route', name='pk_idempotency_keys'),
    )
    op.create_index('ix_idempotency_keys_created_at', 'idempotency_keys', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_idempotency_keys_created_at', table_name='idempotency_keys')
    op.drop_table('idempotency_keys')
    op.drop_index('ix_stripe_events_received_at', table_name='stripe_events')
    op.drop_index('ix_stripe_events_case_id', table_name='stripe_events')
    op.drop_index('ix_stripe_events_event_type', table_name='stripe_events')
    op.drop_table('stripe_events')
