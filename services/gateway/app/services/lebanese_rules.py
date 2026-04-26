"""Lebanese-system specific eligibility rules applied during the
processing pipeline.

These rules encode legal and procedural requirements of the Lebanese
General Directorate of General Security (GDGS / مديرية الأمن العام)
and the Lebanese Civil Registry. They run after OCR but before risk
scoring, so a citizen who submits a structurally-correct application
that nevertheless can't be processed (e.g. trying to renew a pre-2016
non-biometric passport) gets a clear, specific rejection rather than
a confused "manual review" outcome.

Each function returns either None (rule passes) or an EligibilityIssue
describing why the case can't continue and what the citizen should do
instead. The orchestrator collects them and bounces the case to
NEED_INFO with the issue's guidance, or to REJECTED for hard blocks.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass
class EligibilityIssue:
    """A specific Lebanese-rule violation with citizen-facing guidance."""

    code: str
    severity: str           # "block" → reject; "redirect" → need_info with action
    message_ar: str
    message_en: str
    suggested_action: str | None = None   # e.g. "apply_as_passport_new"


# ─────────────────────────────────────────────────────────────────────
#  Passport biometric / pre-2016 rule
# ─────────────────────────────────────────────────────────────────────
#
# Lebanon's biometric passport program launched in 2016. Pre-2016
# passports are non-biometric (older red passport, no embedded chip,
# no machine-readable zone in the modern ICAO 9303 TD3 format). Per
# GDGS rules they cannot be renewed online — the citizen must apply
# as passport_new so fingerprint capture happens in person at a GDGS
# centre.
#
# Detection in order of confidence:
#   1. Passport number prefix: "LR" series is biometric (2016+);
#      anything else (legacy "RL", numeric-only, etc) is pre-2016.
#   2. MRZ parse failure: the OCR service couldn't extract a valid
#      ICAO 9303 TD3 MRZ, which only modern biometric passports carry.
#   3. Issuance date: if extracted from OCR and < 2016-01-01.

BIOMETRIC_PASSPORT_PREFIX = "LR"
BIOMETRIC_PROGRAM_LAUNCH = date(2016, 1, 1)


def check_passport_renewal_eligibility(
    *,
    declared_fields: dict[str, Any],
    ocr_extracted_fields: dict[str, Any],
    mrz_result: dict[str, Any] | None,
) -> EligibilityIssue | None:
    """Apply the pre-2016 / non-biometric rejection rule.

    declared_fields  : whatever the citizen typed (incl. old_passport_number,
                       passport_type, issuance_date if collected).
    ocr_extracted_fields : merged OCR fields across all uploaded documents.
    mrz_result       : the parsed MRZ from the passport data page, or None
                       if MRZ parsing failed entirely.
    """
    declared_number = (declared_fields.get("old_passport_number") or "").strip().upper()
    extracted_number = (ocr_extracted_fields.get("passport_number") or "").strip().upper()
    mrz_number = ((mrz_result or {}).get("passport_number") or "").strip().upper()

    candidates = [n for n in (mrz_number, declared_number, extracted_number) if n]

    # If MRZ parsed cleanly with a non-LR prefix → definitive non-biometric.
    if mrz_number and not mrz_number.startswith(BIOMETRIC_PASSPORT_PREFIX):
        return _non_biometric_issue(mrz_number)

    # If MRZ didn't parse at all but we have *any* number, check it.
    for num in candidates:
        if num and not num.startswith(BIOMETRIC_PASSPORT_PREFIX):
            return _non_biometric_issue(num)

    # MRZ totally absent → very likely a pre-biometric passport that
    # lacks an ICAO 9303 TD3 zone. Flag it.
    if mrz_result is None or not (mrz_result or {}).get("all_checks_passed"):
        # Soft signal — only redirect if we *also* have weak / no
        # extracted passport number with the LR prefix. The MRZ might
        # have failed for image-quality reasons, in which case the
        # quality gate already bounced the case.
        if not any(n.startswith(BIOMETRIC_PASSPORT_PREFIX) for n in candidates):
            return EligibilityIssue(
                code="passport_pre_2016_likely",
                severity="redirect",
                message_ar=(
                    "لم نتمكن من قراءة المنطقة المقروءة آلياً (MRZ) من جواز سفرك القديم. "
                    "إذا كان جواز سفرك صادراً قبل عام 2016 فلا يمكن تجديده عبر الإنترنت — "
                    "الرجاء تقديم طلب جواز سفر جديد عبر الموقع وحضور مركز الأمن العام شخصياً "
                    "للحصول على البصمات."
                ),
                message_en=(
                    "We couldn't read the machine-readable zone on your old passport. "
                    "If it was issued before 2016 it cannot be renewed online — please "
                    "submit a new-passport application instead and visit a GDGS centre "
                    "in person for fingerprint capture."
                ),
                suggested_action="apply_as_passport_new",
            )

    return None


def _non_biometric_issue(number: str) -> EligibilityIssue:
    return EligibilityIssue(
        code="passport_non_biometric",
        severity="redirect",
        message_ar=(
            f"رقم جواز السفر القديم ({number}) ينتمي إلى السلسلة غير البيومترية الصادرة قبل عام 2016. "
            "لا يمكن تجديد الجوازات غير البيومترية عبر الإنترنت — الرجاء تقديم طلب 'جواز سفر جديد' "
            "وحضور مركز الأمن العام شخصياً لأخذ البصمات."
        ),
        message_en=(
            f"Old passport number {number} is from the pre-2016 non-biometric series. "
            "Non-biometric passports cannot be renewed online — please submit a "
            "'new passport' application instead and visit a GDGS centre in person "
            "for fingerprint capture."
        ),
        suggested_action="apply_as_passport_new",
    )


# ─────────────────────────────────────────────────────────────────────
#  Minor (<18) guardian consent rule
# ─────────────────────────────────────────────────────────────────────
#
# Lebanese law requires guardian (وليّ) consent for any passport
# applicant under 18. Practically, the GDGS form needs:
#   - Guardian's national ID (we collect as DocumentType.GUARDIAN_DOCS)
#   - Guardian's consent signature, mukhtar-attested
#   - For both parents alive + married: ideally father's consent;
#     otherwise the recognised legal guardian (single parent, divorced
#     primary custodian, widowed mother, etc).
#
# Birth date can be parsed from declared_fields or the civil registry
# extract OCR. We only enforce the *gate* here — collecting the
# specific guardian-consent doc is handled by the policy engine.

ADULT_AGE_YEARS = 18


def calculate_age(dob: date | str | None, *, ref: date | None = None) -> int | None:
    """Years between dob and `ref` (default today). Returns None if dob
    isn't parseable so callers can decide whether missing-DOB blocks
    or just defers."""
    if dob is None:
        return None
    if isinstance(dob, str):
        try:
            dob = date.fromisoformat(dob)
        except ValueError:
            return None
    today = ref or date.today()
    return today.year - dob.year - (
        (today.month, today.day) < (dob.month, dob.day)
    )


def check_minor_guardian_requirements(
    *,
    declared_fields: dict[str, Any],
    uploaded_doc_types: set[str],
) -> EligibilityIssue | None:
    """If applicant is under 18 and guardian consent isn't on file,
    block submission."""
    age = calculate_age(declared_fields.get("date_of_birth"))
    if age is None or age >= ADULT_AGE_YEARS:
        return None

    # Both docs must be present for a minor — the guardian's ID and
    # the consent form. Treat both as a single doc-type for now since
    # GUARDIAN_DOCS bundles them in the existing schema.
    if "guardian_docs" in uploaded_doc_types:
        return None

    return EligibilityIssue(
        code="minor_guardian_consent_missing",
        severity="redirect",
        message_ar=(
            f"مقدم الطلب قاصر (العمر: {age} سنة). يجب إرفاق موافقة الولي مصدقة من المختار "
            "بالإضافة إلى صورة عن هوية الولي قبل المتابعة."
        ),
        message_en=(
            f"Applicant is a minor (age {age}). A guardian consent form attested by "
            "a mukhtar plus a copy of the guardian's national ID must be uploaded "
            "before the application can proceed."
        ),
        suggested_action="upload_guardian_docs",
    )
