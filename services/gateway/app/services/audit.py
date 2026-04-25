"""Audit logging service - records every automated decision and override.

Every event written here lands in `audit_logs`, which is queryable by
clerks, supervisors, and (eventually) regulators. Anything sensitive
must be redacted on the way in — once a row is committed, its `details`
JSON is essentially permanent and may be replicated to backups, log
sinks, or analytics warehouses.

Redaction strategy:
  - **Names, DOBs, addresses, places of birth** → replaced with the
    constant `"<redacted>"`. We preserve no information about the
    original value because investigators can fetch the actual value
    from `cases.declared_fields` / OCR result tables under access
    control.
  - **High-cardinality identifiers** (passport numbers, national IDs,
    registry numbers, MRZ numbers, emails, phones) → replaced with a
    short SHA-256 hex prefix so two log rows for the same identifier
    can be correlated without reading the original value.
  - **Already-aggregated signals** (confidence floats, risk scores,
    routing decisions) → kept verbatim. They're not PII.

Adding new event types: just put the raw dict in `details=`. The
recursive scrubber walks any nested dict / list and rewrites known
keys, so callers don't need to remember the rules.
"""

from __future__ import annotations

import hashlib
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.request_id import get_request_id

from ..models.audit_log import AuditLog


# Replace value with `"<redacted>"` — no information retained.
_PII_DROP_KEYS: frozenset[str] = frozenset({
    "full_name",
    "full_name_en",
    "full_name_ar",
    "first_name",
    "given_names",
    "surname",
    "family_name",
    "last_name",
    "father_name",
    "mother_name",
    "spouse_name",
    "name",
    "date_of_birth",
    "dob",
    "place_of_birth",
    "address",
    "registry_place",
    "mrz_surname",
    "mrz_given_names",
    "mrz_date_of_birth",
    "mrz_expiry_date",
})

# Replace value with SHA-256 hex prefix — supports correlation across rows.
_PII_HASH_KEYS: frozenset[str] = frozenset({
    "passport_number",
    "old_passport_number",
    "national_id",
    "national_id_number",
    "registry_number",
    "mrz_passport_number",
    "mrz_personal_number",
    "personal_number",
    "email",
    "phone",
    "phone_number",
})

# Keys whose *values* are themselves dicts that follow the same rules
# (e.g. `extracted_fields`, `declared_fields`, `matched_citizen`).
# The recursive scrubber handles them automatically — listed here only
# for documentation.
_NESTED_PII_CONTAINERS: frozenset[str] = frozenset({
    "extracted_fields",
    "declared_fields",
    "matched_citizen",
    "field_results",
    "field_scores",
})

_REDACTED = "<redacted>"


def _hash_token(value: Any) -> str:
    """Stable 12-char hex of the value's string form. Same input → same
    token, so two log rows for the same passport number can be linked
    without exposing the number."""
    digest = hashlib.sha256(str(value).encode("utf-8")).hexdigest()
    return f"<hash:{digest[:12]}>"


def redact_details(value: Any) -> Any:
    """Recursively scrub PII from a log details payload.

    - Dicts: walk every key. If the key is in the drop-list, replace
      the value with `<redacted>`. If hash-list, replace with the
      hashed token. Otherwise recurse into the value.
    - Lists: recurse element-wise.
    - Scalars: returned as-is.
    """
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key_lower = k.lower() if isinstance(k, str) else k
            # Only redact when the value is a non-empty string. Numeric
            # values stored under PII-named keys are *scores about the
            # field*, not the field's content (e.g. confidence_scores
            # keys field names but values are floats).
            is_pii_value = isinstance(v, str) and v != ""
            if key_lower in _PII_DROP_KEYS and is_pii_value:
                out[k] = _REDACTED
            elif key_lower in _PII_HASH_KEYS and is_pii_value:
                out[k] = _hash_token(v)
            else:
                out[k] = redact_details(v)
        return out
    if isinstance(value, list):
        return [redact_details(item) for item in value]
    return value


async def log_action(
    db: AsyncSession,
    action: str,
    user_id: str | None = None,
    case_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> AuditLog:
    rid = get_request_id()
    entry = AuditLog(
        user_id=user_id,
        case_id=case_id,
        action=action,
        details=redact_details(details or {}),
        ip_address=ip_address,
        request_id=None if rid == "-" else rid,
    )
    db.add(entry)
    await db.commit()
    return entry
