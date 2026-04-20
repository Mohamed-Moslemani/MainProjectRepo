"""Fuzzy identity-matching against the civil registry.

Strategy:
  1. If registry_number is supplied, try a direct lookup. The Lebanese
     civil registry uses (registry_number + registry_place) as the
     natural key — a family's ledger entry, essentially.
  2. Score each candidate against the requested fields with fuzzy
     string matching (SequenceMatcher, same as the gateway's
     reconciliation service).
  3. Weighted aggregate → confidence → status.

Field weights reflect how discriminating each field is in Lebanon:
  - registry_number+place: near-unique, high weight
  - date_of_birth: precise, second-highest
  - full_name: noisy (transliteration varies), lower weight
  - father/mother: corroborating, low weight
"""

import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_, func

from ..models.citizen import Citizen
from ..schemas import VerifyRequest, VerifyResponse, MatchedCitizen


FIELD_WEIGHTS: dict[str, float] = {
    "registry_number": 0.30,
    "registry_place": 0.10,
    "date_of_birth": 0.25,
    "full_name": 0.20,
    "father_name": 0.075,
    "mother_name": 0.075,
}


def _normalize(value: str | None) -> str:
    """Lowercase, strip accents, collapse whitespace."""
    if not value:
        return ""
    v = str(value).strip().lower()
    # Strip diacritics (café → cafe; also helps Arabic vowel marks)
    v = "".join(c for c in unicodedata.normalize("NFD", v) if unicodedata.category(c) != "Mn")
    # Collapse whitespace
    v = re.sub(r"\s+", " ", v)
    return v


def _similarity(a: str | None, b: str | None) -> float:
    """Fuzzy 0-1 similarity between two strings after normalization."""
    na, nb = _normalize(a), _normalize(b)
    if not na and not nb:
        return 1.0
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def _parse_date(value) -> date | None:
    """Accept either a date object, ISO string, or DD/MM/YYYY."""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    for fmt_chars in ("/", "-", "."):
        parts = s.split(fmt_chars)
        if len(parts) == 3:
            try:
                # Heuristic: if first part is 4 chars → YYYY-MM-DD; else DD-MM-YYYY
                if len(parts[0]) == 4:
                    y, m, d = map(int, parts)
                else:
                    d, m, y = map(int, parts)
                return date(y, m, d)
            except (ValueError, TypeError):
                continue
    return None


@dataclass
class _CandidateScore:
    citizen: Citizen
    per_field: dict[str, float]
    aggregate: float


def _score_candidate(req: VerifyRequest, citizen: Citizen) -> _CandidateScore:
    scores: dict[str, float] = {}

    scores["registry_number"] = _similarity(req.registry_number, citizen.registry_number)
    scores["registry_place"] = _similarity(req.registry_place, citizen.registry_place)

    # Full name: compare against en AND ar, take the higher.
    req_name = req.full_name or ""
    name_score_en = _similarity(req_name, citizen.full_name_en)
    name_score_ar = _similarity(req_name, citizen.full_name_ar) if citizen.full_name_ar else 0.0
    scores["full_name"] = max(name_score_en, name_score_ar)

    scores["father_name"] = _similarity(req.father_name, citizen.father_name)
    scores["mother_name"] = _similarity(req.mother_name, citizen.mother_name)

    req_dob = _parse_date(req.date_of_birth)
    if req_dob and citizen.date_of_birth:
        scores["date_of_birth"] = 1.0 if req_dob == citizen.date_of_birth else 0.0
    else:
        scores["date_of_birth"] = 0.0

    # Aggregate is a weighted average — but only over fields the requester
    # actually supplied. Fields with no input on the request side don't
    # penalize the score. (You can still match on registry_number alone.)
    total_weight = 0.0
    weighted_sum = 0.0
    requested_fields = _requested_fields(req)
    for field, weight in FIELD_WEIGHTS.items():
        if field not in requested_fields:
            continue
        total_weight += weight
        weighted_sum += weight * scores[field]
    aggregate = weighted_sum / total_weight if total_weight else 0.0

    return _CandidateScore(citizen=citizen, per_field=scores, aggregate=aggregate)


def _requested_fields(req: VerifyRequest) -> set[str]:
    fields = set()
    if req.registry_number:
        fields.add("registry_number")
    if req.registry_place:
        fields.add("registry_place")
    if req.full_name:
        fields.add("full_name")
    if req.father_name:
        fields.add("father_name")
    if req.mother_name:
        fields.add("mother_name")
    if req.date_of_birth:
        fields.add("date_of_birth")
    return fields


async def verify(
    db: AsyncSession,
    req: VerifyRequest,
    exact_threshold: float,
    partial_threshold: float,
) -> VerifyResponse:
    """Search the registry for the best candidate and classify the result."""

    # Build a broad candidate set — we'd rather over-fetch and score than
    # miss a near-hit to a tight SQL filter.
    stmt = select(Citizen)
    clauses = []
    if req.registry_number:
        clauses.append(Citizen.registry_number == req.registry_number)
    if req.registry_place:
        clauses.append(func.lower(Citizen.registry_place) == _normalize(req.registry_place))
    if req.full_name:
        parts = _normalize(req.full_name).split()
        if parts:
            # Match any citizen whose full_name_en shares the first token
            # (cheap prefix-ish filter; exact scoring happens in Python).
            first = parts[0]
            clauses.append(
                or_(
                    func.lower(Citizen.full_name_en).like(f"%{first}%"),
                    func.lower(Citizen.full_name_ar).like(f"%{first}%"),
                )
            )

    if clauses:
        stmt = stmt.where(or_(*clauses))
    stmt = stmt.limit(200)

    result = await db.execute(stmt)
    candidates = list(result.scalars().all())

    if not candidates:
        return VerifyResponse(
            status="no_match",
            confidence=0.0,
            reasons=["No candidate records found in the civil registry"],
        )

    scored = [_score_candidate(req, c) for c in candidates]
    scored.sort(key=lambda s: s.aggregate, reverse=True)
    best = scored[0]

    matched = MatchedCitizen(
        full_name_en=best.citizen.full_name_en,
        full_name_ar=best.citizen.full_name_ar,
        father_name=best.citizen.father_name,
        mother_name=best.citizen.mother_name,
        date_of_birth=best.citizen.date_of_birth,
        registry_number=best.citizen.registry_number,
        registry_place=best.citizen.registry_place,
        municipality=best.citizen.municipality,
        nationality=best.citizen.nationality,
    )

    # Deceased record overrides any status — the ministry wouldn't issue
    # a document to a registered-dead person.
    if best.citizen.deceased and best.aggregate >= partial_threshold:
        return VerifyResponse(
            status="deceased",
            confidence=best.aggregate,
            matched_citizen=matched,
            field_scores={k: round(v, 3) for k, v in best.per_field.items()},
            reasons=[
                "Matched citizen is recorded as deceased in the civil registry",
            ],
        )

    if best.aggregate >= exact_threshold:
        status = "exact_match"
        reasons = []
    elif best.aggregate >= partial_threshold:
        status = "partial_match"
        reasons = _mismatch_reasons(best.per_field)
    else:
        status = "no_match"
        reasons = ["Best candidate scored below the partial-match threshold"]
        matched = None  # don't leak low-confidence hits

    return VerifyResponse(
        status=status,
        confidence=round(best.aggregate, 3),
        matched_citizen=matched,
        field_scores={k: round(v, 3) for k, v in best.per_field.items()},
        reasons=reasons,
    )


def _mismatch_reasons(per_field: dict[str, float]) -> list[str]:
    reasons = []
    for field, score in per_field.items():
        if score < 0.7:
            reasons.append(f"{field} score {score:.2f} below 0.70")
    return reasons
