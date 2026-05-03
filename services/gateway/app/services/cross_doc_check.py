"""Cross-document identity coherence check.

The reconciliation step compares declared_fields against a single
merged dict of all OCR fields. That catches "citizen typed the wrong
thing", but it does NOT catch "citizen uploaded one identity's
passport plus another identity's civil-registry extract" — because
the merged dict last-write-wins on shared keys and the declared
values match whichever doc the citizen identified themselves with.

This module reconciles documents against EACH OTHER. For a renewal
or passport_new flow with ≥2 identity documents, all uploaded docs
must describe the same person. Hard-fail when they don't: this is
the canonical fraud / mismatched-applicant pattern and reaching
"manual_review" for it is not safe enough.

Returns a CrossDocCheckResult dataclass; the orchestrator routes
to REJECTED on `coherent=False` with the per-pair findings as the
audit trail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from rapidfuzz import fuzz

from .reconciliation import normalize


# Field pairs to compare across documents. Keys are the canonical
# field names emitted by the OCR / LLM extractor. Each pair is a
# tuple (label, [doc_keys_that_carry_this_value]) — for a given
# pair, we extract the doc's value from the first key present.
#
# Why the duplication? Different doc types print the same logical
# field under different keys. The passport stores the holder's
# given name as `given_names` (Latin) or `first_name_ar` (Arabic).
# The civil registry stores it as `first_name_ar`. Reconcile both.
IDENTITY_FIELDS = [
    ("first_name", ["first_name_ar", "given_names"]),
    ("surname",    ["surname_ar", "surname"]),
    ("date_of_birth", ["date_of_birth", "mrz_date_of_birth"]),
    ("father_name",   ["father_name"]),
    ("mother_name",   ["mother_name"]),
    ("gender",        ["gender", "mrz_sex", "sex"]),
]

# Per-field minimum similarity to count as "same person". Names are
# fuzzy because OCR + Arabic-Latin transliteration introduces
# noise; DOB and gender must be exact (with light normalisation).
NAME_THRESHOLD = 0.75
EXACT_FIELDS = {"date_of_birth", "gender"}


@dataclass
class FieldDivergence:
    label: str
    doc_a: str
    value_a: str
    doc_b: str
    value_b: str
    similarity: float


@dataclass
class CrossDocCheckResult:
    coherent: bool
    divergences: list[FieldDivergence] = field(default_factory=list)
    docs_compared: list[str] = field(default_factory=list)
    skipped_reason: str | None = None

    def doc_vs_doc_divergences(self) -> list[FieldDivergence]:
        """Only the divergences between two REAL OCR'd docs (excludes
        the virtual 'declared' side). Used by the orchestrator to
        decide hard-reject — declared-vs-doc noise comes mostly from
        OCR misreads, not fraud, and is handled by reconciliation +
        risk scoring (manual review) instead.
        """
        return [
            d for d in self.divergences
            if d.doc_a != "declared" and d.doc_b != "declared"
        ]

    def to_dict(self) -> dict:
        return {
            "coherent": self.coherent,
            "skipped_reason": self.skipped_reason,
            "docs_compared": self.docs_compared,
            "divergences": [
                {
                    "label": d.label,
                    "doc_a": d.doc_a, "value_a": d.value_a,
                    "doc_b": d.doc_b, "value_b": d.value_b,
                    "similarity": round(d.similarity, 4),
                }
                for d in self.divergences
            ],
        }


def _value(ocr_fields: dict, candidate_keys: list[str]) -> str | None:
    for k in candidate_keys:
        v = ocr_fields.get(k)
        if v:
            return str(v).strip()
    return None


def _gender_normalize(v: str) -> str:
    v = (v or "").strip().lower()
    if v in {"m", "male", "ذكر"}:
        return "M"
    if v in {"f", "female", "أنثى", "انثى"}:
        return "F"
    return v


def _dob_normalize(v: str) -> str:
    """Reduce common DOB shapes to YYYY-MM-DD when possible.
    Doesn't fail on weird input — just returns the trimmed string so
    the equality compare sees identical strings produce True."""
    if not v:
        return ""
    s = str(v).strip()
    # Convert common separators
    s = s.replace(".", "-").replace("/", "-")
    parts = s.split("-")
    if len(parts) == 3 and len(parts[0]) == 2 and len(parts[2]) == 4:
        # DD-MM-YYYY → YYYY-MM-DD
        parts = [parts[2], parts[1], parts[0]]
        s = "-".join(parts)
    return s


# Doc types that carry the holder's identity. Excludes selfie /
# liveness_capture / supporting docs (police_report, court_ruling).
IDENTITY_DOC_TYPES = {
    "national_id_front", "national_id_back",
    "old_id_front", "old_id_back",
    "passport_data_page", "old_passport_data_page",
    "civil_registry_extract", "birth_certificate",
}


def _declared_to_identity_fields(declared: dict | None) -> dict[str, str]:
    """Project a case.declared_fields dict onto the OCR field-name space.

    The citizen's account / form data uses unprefixed Latin keys
    (`full_name`, `father_name`, `date_of_birth`). The OCR docs use
    `first_name_ar` / `surname_ar` / `given_names`, etc. Build a
    minimum dict containing whatever overlap is enough for IDENTITY_FIELDS
    candidate-key lookup to find a value.
    """
    if not declared:
        return {}
    out: dict[str, str] = {}
    full = (declared.get("full_name") or "").strip()
    if full:
        # Lebanese citizen accounts store full_name in Arabic. Only
        # project onto the *_ar keys — mapping it onto the Latin
        # `surname`/`given_names` keys would compare Arabic vs Latin
        # transliteration on docs that print both, causing false
        # rejections of legitimate cases. _value()'s candidate-key
        # order [surname_ar, surname] / [first_name_ar, given_names]
        # already prefers Arabic when both sides have it.
        out["surname_ar"] = full
        out["first_name_ar"] = full
    for src, dst in (
        ("father_name", "father_name"),
        ("mother_name", "mother_name"),
        ("date_of_birth", "date_of_birth"),
        ("gender", "gender"),
    ):
        v = declared.get(src)
        if v:
            out[dst] = str(v)
    return out


def check_cross_doc_identity(
    ocr_results_by_doc: dict[str, dict],
    declared_fields: dict | None = None,
) -> CrossDocCheckResult:
    """Verify every identity-bearing document describes the same person.

    Args:
      ocr_results_by_doc: {document_type: ocr_data} where each
        ocr_data has an `extracted_fields` dict. Maps directly from
        results["ocr_results"] in the orchestrator.
      declared_fields: the citizen's typed account / form data
        (case.declared_fields). When present, treated as a virtual
        "declared" identity doc so the check fires even when only one
        identity doc was OCR'd. This is the safety net for the
        case where a wrong-person passport was uploaded but the
        registry extract for some reason didn't get OCR'd —
        declared-vs-passport divergence still catches the fraud.

    Returns CrossDocCheckResult. coherent=True if no field on any
    pair of identity sources diverges below threshold.
    """
    # Filter to identity-bearing docs that actually have extracted fields.
    identity_docs = {
        dt: data.get("extracted_fields") or {}
        for dt, data in ocr_results_by_doc.items()
        if dt in IDENTITY_DOC_TYPES and (data.get("extracted_fields") or {})
    }

    # Project declared_fields onto the same field-name space the OCR
    # docs use, then add it as another "doc" labeled "declared" so the
    # pair-wise comparison loop treats it like any other source.
    declared_proj = _declared_to_identity_fields(declared_fields)
    if declared_proj:
        identity_docs["declared"] = declared_proj

    if len(identity_docs) < 2:
        return CrossDocCheckResult(
            coherent=True,
            skipped_reason=(
                "fewer_than_two_identity_docs"
                if identity_docs else "no_identity_docs"
            ),
            docs_compared=list(identity_docs.keys()),
        )

    divergences: list[FieldDivergence] = []
    doc_types = list(identity_docs.keys())

    # Compare every pair of identity docs on every identity field.
    # O(n²) is fine — typical case has 2-3 identity docs.
    for i in range(len(doc_types)):
        for j in range(i + 1, len(doc_types)):
            dt_a, dt_b = doc_types[i], doc_types[j]
            fields_a, fields_b = identity_docs[dt_a], identity_docs[dt_b]
            for label, candidate_keys in IDENTITY_FIELDS:
                v_a = _value(fields_a, candidate_keys)
                v_b = _value(fields_b, candidate_keys)
                if not v_a or not v_b:
                    # Field missing on one side — not enough
                    # signal to flag a divergence. Reconciliation
                    # against declared_fields will catch the
                    # missing side separately.
                    continue
                if label == "gender":
                    same = _gender_normalize(v_a) == _gender_normalize(v_b)
                    sim = 1.0 if same else 0.0
                elif label == "date_of_birth":
                    same = _dob_normalize(v_a) == _dob_normalize(v_b)
                    sim = 1.0 if same else 0.0
                else:
                    # Use the same Arabic-aware normalisation
                    # reconciliation uses, then token_set_ratio.
                    sim = fuzz.token_set_ratio(normalize(v_a), normalize(v_b)) / 100.0

                threshold = 0.999 if label in EXACT_FIELDS else NAME_THRESHOLD
                if sim < threshold:
                    divergences.append(FieldDivergence(
                        label=label, doc_a=dt_a, value_a=v_a,
                        doc_b=dt_b, value_b=v_b, similarity=sim,
                    ))

    return CrossDocCheckResult(
        coherent=not divergences,
        divergences=divergences,
        docs_compared=doc_types,
    )


def summarize_for_citizen(result: CrossDocCheckResult) -> tuple[str, str]:
    """Produce bilingual one-liner for the citizen-facing retake banner.

    The technical detail (which field on which doc) goes in audit
    logs. The citizen sees "the documents don't appear to belong
    to the same person" — explicit, non-accusatory, actionable.
    """
    if result.coherent:
        return ("", "")
    fields_seen = sorted({d.label for d in result.divergences})
    en = (
        "The documents you uploaded do not appear to describe the same person. "
        f"Mismatching fields across documents: {', '.join(fields_seen)}. "
        "Please ensure every uploaded document belongs to the applicant and re-submit."
    )
    ar = (
        "المستندات التي رفعتها لا تبدو عائدة لنفس الشخص. "
        f"الحقول غير المتطابقة بين المستندات: {', '.join(fields_seen)}. "
        "يرجى التأكد من أن جميع المستندات تخصّ مقدّم الطلب وإعادة التقديم."
    )
    return (ar, en)
