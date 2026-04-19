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
    CaseStatus.PAYMENT_PENDING: {CaseStatus.IN_PRODUCTION},
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
    CaseStatus.REJECTED: "Application rejected. See notes for reason.",
    CaseStatus.IN_PRODUCTION: "Payment received. Your document is being manufactured.",
    CaseStatus.READY_FOR_PICKUP: "Visit the assigned office to collect your document.",
    CaseStatus.CLOSED: "Document collected. Case closed.",
}

FEES: dict[str, int] = {
    "id_new": 2000,              # $20
    "id_renewal": 1500,          # $15
    "passport_new": 6000,        # $60
    "passport_renewal": 4000,    # $40
}


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


def get_fee(service_type: str) -> int:
    return FEES.get(service_type, 0)