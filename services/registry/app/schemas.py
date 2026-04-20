"""Request/response schemas for the civil registry verification API."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class VerifyRequest(BaseModel):
    """Fields the gateway forwards to us — all optional except at least
    one of (registry_number, full_name) must be set to have a search key."""
    full_name: str | None = None
    father_name: str | None = None
    mother_name: str | None = None
    date_of_birth: str | date | None = None   # accept "15/06/1995" or ISO or date
    place_of_birth: str | None = None
    registry_number: str | None = None
    registry_place: str | None = None


class MatchedCitizen(BaseModel):
    full_name_en: str
    full_name_ar: str | None = None
    father_name: str | None = None
    mother_name: str | None = None
    date_of_birth: date | None = None
    registry_number: str
    registry_place: str
    municipality: str | None = None
    nationality: str = "Lebanese"


VerifyStatus = Literal[
    "exact_match",   # all core fields align, high confidence
    "partial_match", # found a likely candidate with 1-2 mismatched fields
    "no_match",      # no credible candidate in the registry
    "deceased",      # found but person is deceased — no document can be issued
]


class VerifyResponse(BaseModel):
    status: VerifyStatus
    confidence: float = Field(ge=0.0, le=1.0)
    matched_citizen: MatchedCitizen | None = None
    field_scores: dict[str, float] = Field(default_factory=dict)  # per-field similarity
    reasons: list[str] = Field(default_factory=list)
    processing_time_ms: int = 0
