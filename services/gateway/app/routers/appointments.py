"""Biometric appointment booking + officer confirmation endpoints.

Citizen-facing:
  GET  /api/v1/appointments/centres            list GDGS centres
  GET  /api/v1/appointments/centres/{id}/slots available 30-min slots
  POST /api/v1/appointments                     book / reschedule (idempotent
                                                 per case)
  GET  /api/v1/cases/{case_id}/appointment      current booking

Officer-facing (admin / clerk role):
  POST /api/v1/admin/appointments/{id}/confirm  mark capture done →
                                                 transitions case to
                                                 IN_PRODUCTION

Slots are 30-minute blocks 09:00-15:00 local Beirut time, weekdays
only — matches GDGS public-counter hours. Capacity is one slot per
centre per slot_start; when a slot is taken it disappears from the
list. Production should pull this from a real GDGS scheduling API.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, time, date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..middleware.auth import get_current_user, require_role
from ..models.biometric_appointment import BiometricAppointment
from ..models.case import Case
from ..models.user import User
from ..services.case_machine import can_transition
from ..services.audit import log_action
from ..services.lebanese_gdgs_centres import GDGS_CENTRES, find_centre, is_valid_centre


router = APIRouter(prefix="/api/v1/appointments", tags=["appointments"])


# ── Schemas ─────────────────────────────────────────────────────

class AppointmentBookRequest(BaseModel):
    case_id: str
    centre_id: str
    slot_start: datetime  # ISO-8601, expected to align to a 30-min boundary


class AppointmentResponse(BaseModel):
    id: str
    case_id: str
    centre_id: str
    centre_name_en: str
    centre_name_ar: str
    slot_start: datetime
    status: str
    confirmed_at: datetime | None

    model_config = {"from_attributes": True}


# ── Centres directory ───────────────────────────────────────────

@router.get("/centres")
async def list_centres():
    """Public list of GDGS centres for the booking dropdown."""
    return {"centres": GDGS_CENTRES}


@router.get("/centres/{centre_id}/slots")
async def list_available_slots(
    centre_id: str,
    days: int = 14,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Available 30-min slots at this centre for the next `days` days.

    Slots are weekdays 09:00 → 15:00 local (Beirut). Booked slots are
    excluded. Returned in UTC to keep the SPA's timezone handling
    uniform.
    """
    if not is_valid_centre(centre_id):
        raise HTTPException(status_code=404, detail="Unknown GDGS centre")

    # Generate the candidate slot grid.
    now_local = datetime.now()
    today = now_local.date()
    slots: list[datetime] = []
    for day_offset in range(days):
        d = today + timedelta(days=day_offset)
        if d.weekday() >= 5:  # 5=Sat, 6=Sun
            continue
        for hour in range(9, 15):
            for minute in (0, 30):
                slot = datetime.combine(d, time(hour=hour, minute=minute))
                if slot <= now_local + timedelta(hours=1):
                    continue   # no same-hour bookings
                slots.append(slot.replace(tzinfo=timezone.utc))

    # Drop slots already booked at this centre.
    if slots:
        booked = await db.execute(
            select(BiometricAppointment.slot_start)
            .where(BiometricAppointment.centre_id == centre_id)
            .where(BiometricAppointment.status.in_(("booked", "rescheduled")))
            .where(BiometricAppointment.slot_start >= slots[0])
            .where(BiometricAppointment.slot_start <= slots[-1])
        )
        taken = {row[0] for row in booked.all()}
        slots = [s for s in slots if s not in taken]

    return {"centre_id": centre_id, "slots": [s.isoformat() for s in slots]}


# ── Citizen booking ──────────────────────────────────────────────

@router.post("", response_model=AppointmentResponse)
async def book_appointment(
    req: AppointmentBookRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Book or reschedule the biometric appointment for a case.

    The case must belong to the calling user and be in
    BIOMETRIC_APPOINTMENT_REQUIRED. Re-booking is allowed up to the
    moment of capture: the existing row gets its slot_start updated
    and status='rescheduled'.
    """
    if not is_valid_centre(req.centre_id):
        raise HTTPException(status_code=400, detail="Unknown GDGS centre")
    if req.slot_start.tzinfo is None:
        req.slot_start = req.slot_start.replace(tzinfo=timezone.utc)
    if req.slot_start <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Slot is in the past")

    case_result = await db.execute(select(Case).where(Case.id == req.case_id))
    case = case_result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")
    if case.status != "biometric_appointment_required":
        raise HTTPException(
            status_code=400,
            detail="Case is not awaiting a biometric appointment",
        )

    # Capacity check — one booking per centre per slot_start.
    clash_result = await db.execute(
        select(BiometricAppointment).where(and_(
            BiometricAppointment.centre_id == req.centre_id,
            BiometricAppointment.slot_start == req.slot_start,
            BiometricAppointment.status.in_(("booked", "rescheduled")),
            BiometricAppointment.case_id != req.case_id,
        ))
    )
    if clash_result.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Slot already taken")

    existing_result = await db.execute(
        select(BiometricAppointment).where(BiometricAppointment.case_id == req.case_id)
    )
    appointment = existing_result.scalar_one_or_none()

    if appointment:
        appointment.centre_id = req.centre_id
        appointment.slot_start = req.slot_start
        appointment.status = "rescheduled"
        action = "appointment_rescheduled"
    else:
        appointment = BiometricAppointment(
            case_id=req.case_id,
            centre_id=req.centre_id,
            slot_start=req.slot_start,
            status="booked",
        )
        db.add(appointment)
        action = "appointment_booked"

    await db.commit()
    await db.refresh(appointment)

    await log_action(
        db, action, user_id=user.id, case_id=req.case_id,
        details={
            "appointment_id": appointment.id,
            "centre_id": req.centre_id,
            "slot_start": req.slot_start.isoformat(),
        },
    )

    centre = find_centre(req.centre_id) or {"en": req.centre_id, "ar": req.centre_id}
    return AppointmentResponse(
        id=appointment.id,
        case_id=appointment.case_id,
        centre_id=appointment.centre_id,
        centre_name_en=centre["en"],
        centre_name_ar=centre["ar"],
        slot_start=appointment.slot_start,
        status=appointment.status,
        confirmed_at=appointment.confirmed_at,
    )


# ── Officer confirmation ────────────────────────────────────────

class ConfirmRequest(BaseModel):
    notes: str | None = None


admin_router = APIRouter(
    prefix="/api/v1/admin/appointments",
    tags=["appointments-admin"],
)


@admin_router.post("/{appointment_id}/confirm")
async def confirm_appointment(
    appointment_id: str,
    body: ConfirmRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_role("clerk", "admin")),
):
    """Officer confirms biometric capture happened. Transitions the
    case from BIOMETRIC_APPOINTMENT_REQUIRED → IN_PRODUCTION."""
    result = await db.execute(
        select(BiometricAppointment).where(BiometricAppointment.id == appointment_id)
    )
    appointment = result.scalar_one_or_none()
    if not appointment:
        raise HTTPException(status_code=404, detail="Appointment not found")
    if appointment.status == "completed":
        return {"status": "already_completed"}

    appointment.status = "completed"
    appointment.confirmed_by_user_id = user.id
    appointment.confirmed_at = datetime.now(timezone.utc)

    case_result = await db.execute(select(Case).where(Case.id == appointment.case_id))
    case = case_result.scalar_one_or_none()
    if case and can_transition(case.status, "in_production"):
        case.status = "in_production"
        case.status_history = case.status_history + [{
            "status": "in_production",
            "message": "Biometrics captured at GDGS centre — production started",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "actor": f"officer:{user.full_name}",
        }]

    await db.commit()
    await log_action(
        db, "appointment_confirmed", user_id=user.id, case_id=appointment.case_id,
        details={"appointment_id": appointment_id, "notes": body.notes},
    )
    return {"status": "completed", "case_status": case.status if case else None}


# ── Lookup endpoint for citizen UI ───────────────────────────────

case_router = APIRouter(prefix="/api/v1/cases", tags=["cases"])


@case_router.get("/{case_id}/appointment")
async def get_case_appointment(
    case_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    case_result = await db.execute(select(Case).where(Case.id == case_id))
    case = case_result.scalar_one_or_none()
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    if case.user_id != user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await db.execute(
        select(BiometricAppointment).where(BiometricAppointment.case_id == case_id)
    )
    appointment = result.scalar_one_or_none()
    if not appointment:
        return {"appointment": None}

    centre = find_centre(appointment.centre_id) or {"en": appointment.centre_id, "ar": appointment.centre_id}
    return {
        "appointment": {
            "id": appointment.id,
            "centre_id": appointment.centre_id,
            "centre_name_en": centre["en"],
            "centre_name_ar": centre["ar"],
            "slot_start": appointment.slot_start.isoformat(),
            "status": appointment.status,
            "confirmed_at": appointment.confirmed_at.isoformat() if appointment.confirmed_at else None,
        }
    }
