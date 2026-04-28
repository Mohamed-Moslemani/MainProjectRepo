"""add_outbox_and_biometric_appointment

Revision ID: a1b2c3d4e5f6
Revises: f3a8d2c1b6e7
Create Date: 2026-04-28 02:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'f3a8d2c1b6e7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Email outbox — durable transactional pattern for SMTP.
    op.create_table(
        'email_outbox',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('to_email', sa.String(), nullable=False),
        sa.Column('subject', sa.String(), nullable=False),
        sa.Column('html_body', sa.Text(), nullable=False),
        sa.Column('email_type', sa.String(), nullable=False),
        sa.Column('metadata', sa.JSON(), nullable=False, server_default='{}'),
        sa.Column('status', sa.String(), nullable=False, server_default='pending'),
        sa.Column('attempt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('next_attempt_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_email_outbox_to_email', 'email_outbox', ['to_email'])
    op.create_index('ix_email_outbox_email_type', 'email_outbox', ['email_type'])
    op.create_index('ix_email_outbox_status', 'email_outbox', ['status'])
    op.create_index('ix_email_outbox_created_at', 'email_outbox', ['created_at'])
    op.create_index('ix_email_outbox_next_attempt_at', 'email_outbox', ['next_attempt_at'])

    # Biometric appointments — passport_new mandatory in-person step.
    op.create_table(
        'biometric_appointments',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('case_id', sa.String(), nullable=False),
        sa.Column('centre_id', sa.String(), nullable=False),
        sa.Column('slot_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='booked'),
        sa.Column('confirmed_by_user_id', sa.String(), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['case_id'], ['cases.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['confirmed_by_user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('case_id', name='uq_biometric_appointments_case_id'),
    )
    op.create_index('ix_biometric_appointments_centre_id', 'biometric_appointments', ['centre_id'])
    op.create_index('ix_biometric_appointments_slot_start', 'biometric_appointments', ['slot_start'])
    op.create_index('ix_biometric_appointments_status', 'biometric_appointments', ['status'])


def downgrade() -> None:
    op.drop_index('ix_biometric_appointments_status', table_name='biometric_appointments')
    op.drop_index('ix_biometric_appointments_slot_start', table_name='biometric_appointments')
    op.drop_index('ix_biometric_appointments_centre_id', table_name='biometric_appointments')
    op.drop_table('biometric_appointments')

    op.drop_index('ix_email_outbox_next_attempt_at', table_name='email_outbox')
    op.drop_index('ix_email_outbox_created_at', table_name='email_outbox')
    op.drop_index('ix_email_outbox_status', table_name='email_outbox')
    op.drop_index('ix_email_outbox_email_type', table_name='email_outbox')
    op.drop_index('ix_email_outbox_to_email', table_name='email_outbox')
    op.drop_table('email_outbox')
