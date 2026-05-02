"""Cross-document identity check — coverage for all 4 service flows.

Each test pair runs the same scenario twice — once with the citizen's
own data (legitimate, must pass) and once with another person's data
swapped into the identity-bearing OCR doc (fraud, must hard-reject).

The point of this file: prevent regressions like DFL-121F9135 where a
passport_renewal fraud submission slipped past the cross-doc check
because the policy left the registry extract out of `ocr_documents`.

The fixtures below mirror what the OCR service actually emits per
document type — same field names, Arabic + Latin pairs, MRZ block on
passports — so changes to the OCR schemas are caught by these tests.
"""

from __future__ import annotations

import pytest

from app.services.cross_doc_check import (
    IDENTITY_DOC_TYPES,
    check_cross_doc_identity,
)


# ── Citizen identity ──
# A single canonical "real you" used as the legitimate baseline.
# The fraud variant swaps a different person into the OCR doc that
# would normally carry holder identity.
DECLARED_LEGIT = {
    "full_name": "محمد مسلماني",
    "father_name": "علي",
    "mother_name": "زهرة أيوب",
    "date_of_birth": "2000-08-03",
    "place_of_birth": "صور",
    "gender": "M",
    "registry_number": "53",
    "registry_place": "Tyre",
}


def _registry_extract(*, holder: str = "self") -> dict:
    """OCR fields that come off a Lebanese civil-registry extract."""
    if holder == "self":
        return {
            "first_name_ar": "محمد",
            "surname_ar": "مسلماني",
            "father_name": "علي",
            "mother_name": "زهرة أيوب",
            "date_of_birth": "2000-08-03",
            "place_of_birth": "صور",
            "gender": "ذكر",
            "id_number": "00004660178",
            "register_place": "الشعيتية 53",
            "district": "صور",
        }
    # "mom" — name + DOB swapped to a different person, everything else
    # incidental. Same shape mom's actual registry extract would produce.
    return {
        "first_name_ar": "زهرة",
        "surname_ar": "أيوب",
        "father_name": "سعيد",
        "mother_name": "زينب قليط",
        "date_of_birth": "1961-01-12",
        "place_of_birth": "بوكيه",
        "gender": "أنثى",
    }


def _passport_data_page(*, holder: str = "self") -> dict:
    if holder == "self":
        return {
            "surname": "MOSLEIMANI", "surname_ar": "مسلماني",
            "given_names": "MOHAMED", "first_name_ar": "محمد",
            "father_name": "علي", "mother_name": "زهرة أيوب",
            "date_of_birth": "2000-08-03", "place_of_birth": "TYRE",
            "sex": "M", "passport_number": "LR1234567", "nationality": "LBN",
            "mrz_passport_number": "LR1234567", "mrz_surname": "MOSLEIMANI",
            "mrz_given_names": "MOHAMED", "mrz_date_of_birth": "2000-08-03",
            "mrz_sex": "M", "mrz_nationality": "LBN",
        }
    return {
        "surname": "AYOUB", "surname_ar": "أيوب",
        "given_names": "ZAHRA", "first_name_ar": "زهره",
        "father_name": "سعيد", "mother_name": "زينب قليط",
        "date_of_birth": "1961-01-12", "place_of_birth": "BOUKIE",
        "sex": "F", "passport_number": "LR3044513", "nationality": "LBN",
        "mrz_passport_number": "LR3044513", "mrz_surname": "AYOUB",
        "mrz_given_names": "ZAHRA", "mrz_date_of_birth": "1961-01-12",
        "mrz_sex": "F", "mrz_nationality": "LBN",
    }


def _id_front(*, holder: str = "self") -> dict:
    if holder == "self":
        return {
            "first_name_ar": "محمد", "surname_ar": "مسلماني",
            "father_name": "علي", "mother_name": "زهرة أيوب",
            "date_of_birth": "2000-08-03", "place_of_birth": "صور",
            "gender": "ذكر", "id_number": "00004660178",
        }
    return {
        "first_name_ar": "زهرة", "surname_ar": "أيوب",
        "father_name": "سعيد", "mother_name": "زينب قليط",
        "date_of_birth": "1961-01-12", "gender": "أنثى",
        "id_number": "00012345678",
    }


def _id_back() -> dict:
    """ID back face — no holder name, only registry/sect/marital."""
    return {
        "id_number": "00004660178",
        "issue_date": "2024-05-12",
        "register_place": "الشعيتية 53",
        "district": "صور",
        "religious_sect": "شيعي",
        "marital_status": "أعزب",
    }


def _wrap(d: dict) -> dict:
    """Match the `{document_type: {extracted_fields: {...}}}` shape the
    orchestrator passes to check_cross_doc_identity()."""
    return {"extracted_fields": d}


# ── Per-flow OCR sets ──
# Each builder takes a `fraudulent_doc` arg naming which slot to swap
# someone else's identity into. None = full legit upload.
def ocr_set_id_new(fraudulent_doc: str | None = None) -> dict:
    return {
        "civil_registry_extract": _wrap(
            _registry_extract(holder="mom" if fraudulent_doc == "civil_registry_extract" else "self")
        ),
    }


def ocr_set_id_renewal(fraudulent_doc: str | None = None) -> dict:
    return {
        "old_id_front": _wrap(
            _id_front(holder="mom" if fraudulent_doc == "old_id_front" else "self")
        ),
        "old_id_back": _wrap(_id_back()),
        "civil_registry_extract": _wrap(
            _registry_extract(holder="mom" if fraudulent_doc == "civil_registry_extract" else "self")
        ),
    }


def ocr_set_passport_new(fraudulent_doc: str | None = None) -> dict:
    return {
        "national_id_front": _wrap(
            _id_front(holder="mom" if fraudulent_doc == "national_id_front" else "self")
        ),
        "national_id_back": _wrap(_id_back()),
        "civil_registry_extract": _wrap(
            _registry_extract(holder="mom" if fraudulent_doc == "civil_registry_extract" else "self")
        ),
    }


def ocr_set_passport_renewal(fraudulent_doc: str | None = None) -> dict:
    # NB: relies on the post-DFL-121F9135 policy patch that puts
    # CIVIL_REGISTRY_EXTRACT back into ocr_documents for passport_renewal.
    # If that regresses, this flow's "mom's passport + my registry" case
    # will skip with fewer_than_two_identity_docs and the test will fail.
    return {
        "old_passport_data_page": _wrap(
            _passport_data_page(holder="mom" if fraudulent_doc == "old_passport_data_page" else "self")
        ),
        "civil_registry_extract": _wrap(
            _registry_extract(holder="mom" if fraudulent_doc == "civil_registry_extract" else "self")
        ),
    }


FLOW_BUILDERS = {
    "id_new": ocr_set_id_new,
    "id_renewal": ocr_set_id_renewal,
    "passport_new": ocr_set_passport_new,
    "passport_renewal": ocr_set_passport_renewal,
}


# ── Tests ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("flow", list(FLOW_BUILDERS.keys()))
def test_legit_submission_passes(flow):
    """All four flows: own docs + own declared fields → coherent."""
    ocr = FLOW_BUILDERS[flow](fraudulent_doc=None)
    result = check_cross_doc_identity(ocr, declared_fields=DECLARED_LEGIT)
    assert result.coherent, (
        f"{flow}: expected coherent but got divergences "
        f"{[(d.label, d.doc_a, d.doc_b) for d in result.divergences]}"
    )
    assert result.skipped_reason is None, f"{flow}: unexpected skip {result.skipped_reason}"


@pytest.mark.parametrize(
    "flow,fraudulent_doc",
    [
        ("id_new", "civil_registry_extract"),
        ("id_renewal", "old_id_front"),
        ("id_renewal", "civil_registry_extract"),
        ("passport_new", "national_id_front"),
        ("passport_new", "civil_registry_extract"),
        ("passport_renewal", "old_passport_data_page"),
        ("passport_renewal", "civil_registry_extract"),
    ],
)
def test_fraud_submission_rejected(flow, fraudulent_doc):
    """Swap one identity doc for another person's — must hard-reject.

    `fraudulent_doc` names the slot we corrupted. The test passes if
    the check returns coherent=False with at least one divergence
    naming that doc OR the declared/declared-vs-doc divergence (the
    declared row is the safety-net against single-doc OCR).
    """
    ocr = FLOW_BUILDERS[flow](fraudulent_doc=fraudulent_doc)
    result = check_cross_doc_identity(ocr, declared_fields=DECLARED_LEGIT)
    assert not result.coherent, (
        f"{flow} (fraud in {fraudulent_doc}): expected NOT coherent "
        f"but got skipped={result.skipped_reason}, divergences=0"
    )
    # The fraudulent doc must surface in at least one divergence
    # (either against another OCR doc or against `declared`).
    docs_in_divergences = {d.doc_a for d in result.divergences} | {
        d.doc_b for d in result.divergences
    }
    assert fraudulent_doc in docs_in_divergences, (
        f"{flow} (fraud in {fraudulent_doc}): the fraudulent doc is not "
        f"named in any divergence. Divergences: "
        f"{[(d.label, d.doc_a, d.doc_b) for d in result.divergences]}"
    )


def test_declared_fields_included_as_identity_source():
    """When only one identity doc is OCR'd, the citizen's declared
    fields must still trigger the divergence check — this is the bug
    that let DFL-121F9135 slip through."""
    ocr_only_passport = ocr_set_passport_renewal(fraudulent_doc="old_passport_data_page")
    # Drop the registry so we have a 1-OCR-doc submit.
    ocr_only_passport.pop("civil_registry_extract")
    result = check_cross_doc_identity(ocr_only_passport, declared_fields=DECLARED_LEGIT)
    assert not result.coherent
    assert result.skipped_reason is None, (
        "with declared_fields present, should not skip on <2 OCR docs"
    )
    assert "declared" in result.docs_compared
    assert "old_passport_data_page" in result.docs_compared


def test_no_declared_fields_and_one_doc_skips_safely():
    """Backwards-compat: a 1-OCR-doc submit with empty declared_fields
    skips with the documented reason instead of crashing."""
    ocr_only = {"civil_registry_extract": _wrap(_registry_extract(holder="self"))}
    result = check_cross_doc_identity(ocr_only, declared_fields=None)
    assert result.coherent
    assert result.skipped_reason == "fewer_than_two_identity_docs"


def test_legit_passport_renewal_with_both_docs_and_declared():
    """The fix for DFL-121F9135: passport_renewal with both passport +
    registry + matching declared fields must remain coherent (no false
    positives from the new declared-vs-doc pair-wise comparisons)."""
    ocr = ocr_set_passport_renewal(fraudulent_doc=None)
    result = check_cross_doc_identity(ocr, declared_fields=DECLARED_LEGIT)
    assert result.coherent, (
        "legit passport_renewal regressed — divergences: "
        f"{[(d.label, d.doc_a, d.doc_b, d.value_a, d.value_b) for d in result.divergences]}"
    )
    # All three identity sources should be in the comparison set.
    assert set(result.docs_compared) == {
        "old_passport_data_page", "civil_registry_extract", "declared",
    }


def test_identity_doc_types_covers_all_holder_carrying_docs():
    """If a new identity doc is added to the OCR pipeline but not
    declared as identity-bearing, the cross-doc check silently ignores
    it — exactly the failure mode that produced DFL-121F9135. Lock in
    the current set so additions get reviewed."""
    expected = {
        "national_id_front", "national_id_back",
        "old_id_front", "old_id_back",
        "passport_data_page", "old_passport_data_page",
        "civil_registry_extract", "birth_certificate",
    }
    assert IDENTITY_DOC_TYPES == expected
