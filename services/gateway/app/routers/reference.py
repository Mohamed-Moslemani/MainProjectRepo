"""Static reference data the frontend renders into dropdowns.

Sects, GDGS centres, renewal reasons, passport-validity tiers — all
of these are server-owned enums we don't want hard-coded in the
React bundle. Keeping them on the gateway means the policy engine
and the UI agree by construction.

These endpoints are unauthenticated; the data is public-knowledge
reference material (the 18 sects are constitutional, the GDGS
centre list is on the GDGS website).
"""

from __future__ import annotations

from fastapi import APIRouter

from ..services.lebanese_sects import SECTS
from ..services.lebanese_gdgs_centres import GDGS_CENTRES
from ..services.case_machine import (
    valid_passport_validity_years,
    PASSPORT_FEES_BY_VALIDITY,
)


router = APIRouter(prefix="/api/v1/reference", tags=["reference"])


@router.get("/sects")
async def list_sects():
    """The 18 officially-recognised Lebanese religious sects."""
    return {"sects": SECTS}


@router.get("/gdgs-centres")
async def list_gdgs_centres():
    """The 9 GDGS biometric-capture centres (governorate hubs)."""
    return {"centres": GDGS_CENTRES}


@router.get("/passport-validity")
async def list_passport_validity():
    """Allowed passport validity tiers + their fees in cents."""
    years = valid_passport_validity_years()
    return {
        "options": [
            {
                "years": y,
                # Both passport service types share the same fee tier
                # today; expose `fee_cents` for the common case and
                # `fees_by_service` for completeness.
                "fee_cents": PASSPORT_FEES_BY_VALIDITY[y]["passport_new"],
                "fees_by_service": PASSPORT_FEES_BY_VALIDITY[y],
            }
            for y in years
        ]
    }


@router.get("/renewal-reasons")
async def list_renewal_reasons():
    """Lebanese GDGS passport-renewal reason categories.

    Each reason maps to specific supporting documents; the policy
    engine appends those to required_documents at submit time.
    """
    return {
        "reasons": [
            {"id": "expired",     "ar": "انتهاء الصلاحية", "en": "Expired",
             "extra_docs": []},
            {"id": "lost",        "ar": "فقدان",            "en": "Lost",
             "extra_docs": ["police_report"]},
            {"id": "stolen",      "ar": "سرقة",              "en": "Stolen",
             "extra_docs": ["police_report"]},
            {"id": "damaged",     "ar": "تلف",               "en": "Damaged",
             "extra_docs": ["damaged_passport"]},
            {"id": "pages_full",  "ar": "نفاد الصفحات",     "en": "Pages full",
             "extra_docs": []},
            {"id": "name_change", "ar": "تغيير الاسم",      "en": "Name change",
             "extra_docs": ["court_ruling"]},
        ]
    }
