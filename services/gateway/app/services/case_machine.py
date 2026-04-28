"""Case state machine - defines valid transitions, next actions, and fees.

State flow:
  ID services:
    DRAFT -> SUBMITTED -> VALIDATED -> RISK_EVALUATED ->
      APPROVED / REJECTED / NEED_INFO
    APPROVED -> PAYMENT_PENDING -> IN_PRODUCTION -> READY_FOR_PICKUP -> CLOSED

  Passport services (mukhtar approval required):
    DRAFT -> SUBMITTED -> VALIDATED -> RISK_EVALUATED ->
      PENDING_MUKHTAR / REJECTED / NEED_INFO
    PENDING_MUKHTAR -> APPROVED / REJECTED / NEED_INFO  (mukhtar decides)
    APPROVED -> PAYMENT_PENDING -> IN_PRODUCTION -> READY_FOR_PICKUP -> CLOSED

  NEED_INFO -> SUBMITTED (re-submit after fixing)
"""

from shared.schemas import CaseStatus

TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    CaseStatus.DRAFT: {CaseStatus.SUBMITTED},
    CaseStatus.SUBMITTED: {CaseStatus.VALIDATED, CaseStatus.NEED_INFO, CaseStatus.REJECTED},
    CaseStatus.VALIDATED: {CaseStatus.RISK_EVALUATED},
    CaseStatus.RISK_EVALUATED: {
        CaseStatus.APPROVED, CaseStatus.REJECTED, CaseStatus.NEED_INFO,
        CaseStatus.PENDING_MUKHTAR,
    },
    CaseStatus.PENDING_MUKHTAR: {CaseStatus.APPROVED, CaseStatus.REJECTED, CaseStatus.NEED_INFO},
    CaseStatus.NEED_INFO: {CaseStatus.SUBMITTED},
    CaseStatus.APPROVED: {CaseStatus.PAYMENT_PENDING},
    # passport_new pays first, then must do in-person biometrics
    # before production. id_renewal / passport_renewal go straight to
    # IN_PRODUCTION since their biometrics are already on file.
    CaseStatus.PAYMENT_PENDING: {
        CaseStatus.IN_PRODUCTION,
        CaseStatus.BIOMETRIC_APPOINTMENT_REQUIRED,
        CaseStatus.PAYMENT_FAILED,
    },
    # Stripe webhook said the charge failed; citizen retries by
    # creating a new checkout session, which moves them back to
    # PAYMENT_PENDING. Allow REJECTED too so a clerk can give up on
    # a case after N failures.
    CaseStatus.PAYMENT_FAILED: {CaseStatus.PAYMENT_PENDING, CaseStatus.REJECTED},
    # Officer confirms biometric capture done at the kiosk →
    # IN_PRODUCTION. NEED_INFO if the citizen no-showed and the
    # appointment needs rebooking.
    CaseStatus.BIOMETRIC_APPOINTMENT_REQUIRED: {
        CaseStatus.IN_PRODUCTION,
        CaseStatus.NEED_INFO,
    },
    CaseStatus.REJECTED: set(),
    CaseStatus.IN_PRODUCTION: {CaseStatus.READY_FOR_PICKUP},
    CaseStatus.READY_FOR_PICKUP: {CaseStatus.CLOSED},
    CaseStatus.CLOSED: set(),
}

NEXT_ACTIONS: dict[CaseStatus, str] = {
    CaseStatus.DRAFT: "Complete your application and upload required documents.",
    CaseStatus.SUBMITTED: "Your application is being processed. Please wait.",
    CaseStatus.VALIDATED: "Documents validated. Risk assessment in progress.",
    CaseStatus.RISK_EVALUATED: "Risk assessment complete. Pending decision.",
    CaseStatus.NEED_INFO: "Additional information required. Check details and re-submit.",
    CaseStatus.PENDING_MUKHTAR: "Awaiting Mukhtar verification and digital stamp.",
    CaseStatus.APPROVED: "Application approved. Please proceed to payment.",
    CaseStatus.PAYMENT_PENDING: "Payment required. Complete payment to proceed.",
    CaseStatus.PAYMENT_FAILED: "Payment failed. Please retry — your application is held until payment clears.",
    CaseStatus.BIOMETRIC_APPOINTMENT_REQUIRED: (
        "Book and attend a GDGS centre appointment for fingerprint capture. "
        "Bring your national ID and the printed payment receipt."
    ),
    CaseStatus.REJECTED: "Application rejected. See notes for reason.",
    CaseStatus.IN_PRODUCTION: "Payment received. Your document is being manufactured.",
    CaseStatus.READY_FOR_PICKUP: "Visit the assigned office to collect your document.",
    CaseStatus.CLOSED: "Document collected. Case closed.",
}

# ── Fee schedule ────────────────────────────────────────────────────
#
# All values in cents. The Lebanese General Directorate of General
# Security publishes passport fees on a sliding scale by validity
# duration; ID-card fees are flat. The numbers below mirror the
# post-2023 USD-pegged tariff GDGS adopted after the LBP collapse —
# they're easy to revise via a single env override
# (DOCFLOW_FEES_OVERRIDE_JSON) when GDGS publishes a new schedule
# without forcing a code change.
ID_FEES: dict[str, int] = {
    "id_new": 2000,              # $20
    "id_renewal": 1500,          # $15
}

# Passport fees vary by *validity*. Citizens pick a duration at
# checkout; the orchestrator stamps it onto the case and the payment
# layer reads it here. Numbers are USD cents.
PASSPORT_FEES_BY_VALIDITY: dict[int, dict[str, int]] = {
    1:  {"passport_new":  5000, "passport_renewal": 5000},   # $50
    3:  {"passport_new":  8000, "passport_renewal": 8000},   # $80
    5:  {"passport_new": 15000, "passport_renewal": 15000},  # $150
    10: {"passport_new": 30000, "passport_renewal": 30000},  # $300
}

# Default validity if the citizen didn't pick one yet — defensive
# fallback so a half-completed application still has a quoted price.
DEFAULT_PASSPORT_VALIDITY_YEARS = 5


def can_transition(current: str, target: str) -> bool:
    try:
        current_status = CaseStatus(current)
        target_status = CaseStatus(target)
    except ValueError:
        return False
    return target_status in TRANSITIONS.get(current_status, set())


def get_next_action(status: str) -> str | None:
    try:
        return NEXT_ACTIONS.get(CaseStatus(status))
    except ValueError:
        return None


def get_fee(service_type: str, declared_fields: dict | None = None) -> int:
    """Compute the GDGS fee for a case in cents.

    For ID services the fee is flat. For passport services the fee
    scales by chosen validity (1 / 3 / 5 / 10 years), pulled from
    declared_fields["passport_validity_years"] — falls back to
    DEFAULT_PASSPORT_VALIDITY_YEARS when not picked yet.
    """
    if service_type in ID_FEES:
        return ID_FEES[service_type]

    if service_type in ("passport_new", "passport_renewal"):
        validity = (declared_fields or {}).get("passport_validity_years")
        try:
            validity_int = int(validity) if validity is not None else DEFAULT_PASSPORT_VALIDITY_YEARS
        except (TypeError, ValueError):
            validity_int = DEFAULT_PASSPORT_VALIDITY_YEARS
        tier = PASSPORT_FEES_BY_VALIDITY.get(validity_int)
        if tier is None:
            # Unsupported validity — quote the default so payment
            # doesn't 500. Validation should have caught this earlier.
            tier = PASSPORT_FEES_BY_VALIDITY[DEFAULT_PASSPORT_VALIDITY_YEARS]
        return tier.get(service_type, 0)

    return 0


def valid_passport_validity_years() -> list[int]:
    """The validities a citizen is allowed to pick. Used by the
    declared-fields validator and the SPA to render the dropdown."""
    return sorted(PASSPORT_FEES_BY_VALIDITY.keys())