"""unique appointment slot per centre

Adds a partial unique index on (centre_id, slot_start) for active
appointments so two citizens cannot race the booking endpoint and
both win the same 30-minute slot at the same GDGS centre.

Without this, the application-level "is the slot taken?" check
(appointments.py) is racy under concurrent submissions and will
silently overbook. The partial index covers only booked / rescheduled
rows, so a cancelled or completed appointment doesn't block re-booking
of the same slot.

Revision ID: c2e3f4a5b601
Revises: b7c8d9e0a1b2
Create Date: 2026-05-02 12:00:00
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'c2e3f4a5b601'
down_revision: Union[str, Sequence[str], None] = 'b7c8d9e0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_centre_slot_active
            ON biometric_appointments (centre_id, slot_start)
            WHERE status IN ('booked', 'rescheduled')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_appointments_centre_slot_active")
