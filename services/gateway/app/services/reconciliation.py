"""Reconciliation — declared-vs-extracted field comparison.

Problem this module solves:

The citizen types declared values into the form (Arabic, often by hand,
sometimes from a phone keyboard that injects diacritics or Eastern
Arabic numerals). The OCR + LLM pipeline extracts values from the
photographed civil-registry extract. Both produce *correct* values
that don't compare equal as raw strings:

  declared:   "صور"
  extracted:  "صور"      ← identical to the eye, not byte-equal
                            (different alef-with-hamza, trailing
                            zero-width-joiner, NBSP, …)

  declared:   "محمد مسلماني"
  extracted:  "محمد المسلماني"   ← prefix difference

  declared:   "53"
  extracted:  "٥٣"        ← Eastern Arabic digits

Without normalization, every match becomes a mismatch and reconciliation
auto-rejects legitimate citizens.

Approach:

1. Aggressive *Arabic-aware* normalization — NFKC, hamza-fold,
   ya/alef-maksura fold, teh-marbuta -> heh, diacritics stripped,
   tatweel removed, Eastern->Western digits, whitespace collapsed.
2. Fuzzy matching on top — rapidfuzz token_set_ratio handles
   re-ordered name parts ("علي محمد" vs "محمد علي") and partial
   surname matches ("الشهرة" returning "مسلماني" vs declared
   "محمد مسلماني").
3. Numeric fields (DOB, registry_number, ID number) compared as
   normalised strings — ٢٠٠٠/٠٨/٠٣ == 2000-08-03 after digit fold.

Output shape kept identical to the previous implementation so
downstream consumers (orchestrator, FE, audit log) don't change.
"""

from __future__ import annotations

import logging
import re
import unicodedata

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - dev environments without rapidfuzz
    fuzz = None

logger = logging.getLogger(__name__)


# Field mapping: declared field -> ordered list of OCR fields to
# consult. The matcher tries each candidate key and keeps the best
# fuzzy score. For full_name we look at the synthesised full_name_ar
# (built by field_extractor.py from the first_name_ar + surname_ar
# cells found on real Lebanese IDs and civil-registry extracts) AND
# at the individual part keys, so a citizen's declared "Mohamed Saad"
# scores high against either the joined cell or the surname alone.
# Latin-script keys (full_name_en, given_names, surname) cover
# passports, which DO print Latin alongside Arabic.
FIELD_MAPPING = {
    "full_name":   ["full_name_ar", "full_name", "full_name_en", "surname",
                    "surname_ar", "first_name_ar", "given_names"],
    "first_name":  ["first_name_ar", "given_names"],
    "last_name":   ["surname_ar", "surname"],
    "surname":     ["surname_ar", "surname"],
    "father_name": ["father_name"],
    "mother_name": ["mother_name"],
    "date_of_birth": ["date_of_birth", "mrz_date_of_birth"],
    "registry_number": ["registry_number", "id_number", "register_number",
                        "mrz_passport_number"],
    "registry_place": ["register_place", "registry_place"],
    "place_of_birth": ["place_of_birth"],
    "old_passport_number": ["passport_number", "mrz_passport_number"],
    "gender": ["gender", "mrz_sex"],
    "religious_sect": ["religious_sect"],
    "marital_status": ["marital_status"],
    "district": ["district"],
}

# Score thresholds. token_set_ratio scales 0-100; we read it as 0-1.
MATCH_THRESHOLD = 0.85
MISMATCH_THRESHOLD = 0.5

# Declared fields that have NO document analog — they're citizen-typed
# metadata (renewal reason, requested validity tier, marital status,
# residential address). Including them in reconciliation would always
# produce "not_found_in_ocr" which drags integrity_score down for
# perfectly-clean cases. Filter them out before scoring; they're still
# kept in case.declared_fields for the audit trail and the mukhtar form.
SKIP_RECONCILIATION_FIELDS = {
    "passport_validity_years",  # citizen picks 1y/3y/5y/10y at submit
    "renewal_reason",            # passport_renewal: expired / damaged / lost / name_change
    "reason_for_renewal",        # id_renewal: same idea, different name
    "passport_type",             # ordinary / diplomatic / service
    "marital_status",            # never on a national ID
    "address",                   # residential, optional, never on a doc
    "phone",                     # contact field, not a doc field
    "religious_sect",            # printed only on civil-registry extract;
                                 # reconciled separately when present in OCR
    "municipality",              # mukhtar jurisdiction routing only
}


# ── Arabic normalization ─────────────────────────────────────────────

# Eastern + Persian Arabic digits → Western Arabic digits (0-9).
_DIGIT_MAP = str.maketrans({
    # Arabic-Indic digits (U+0660..U+0669)
    "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
    "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9",
    # Extended Arabic-Indic / Persian digits (U+06F0..U+06F9)
    "۰": "0", "۱": "1", "۲": "2", "۳": "3", "۴": "4",
    "۵": "5", "۶": "6", "۷": "7", "۸": "8", "۹": "9",
})

# Hamza variants → bare alef. Ya variants → bare ya. Teh-marbuta → heh.
# These are the standard "imperfect-search" folds Arabic NLP libraries
# use; they collapse forms a citizen and a printer might use
# interchangeably.
_LETTER_MAP = str.maketrans({
    "أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا",
    "ى": "ي",
    "ة": "ه",
    # Common Persian/Urdu/Pashto variants that show up in scanned text
    "ﻱ": "ي", "ﻲ": "ي", "ﻳ": "ي", "ﻴ": "ي",
    "ك": "ك",   # Arabic kaf (already Arabic, but normalise from Persian
    "ک": "ك",   # Persian kaf
    # Tatweel — kashida / elongation char, has no semantic value
    "ـ": "",
})

# Tashkeel (diacritics) range we strip wholesale. Includes shadda,
# fatha, kasra, damma, tanween, sukun, and Quranic marks.
_TASHKEEL_RE = re.compile("[ً-ٰٟۖ-ۭ]")
# Zero-width chars + bidi controls + various joiners that copy-paste
# from PDFs/forms drag along.
_ZW_RE = re.compile("[​-‏‪-‮⁦-⁩﻿]")
# Anything not letter/digit/space after stripping → drop. Keeps
# Arabic + Latin + numbers; drops "/", "-", ".", etc.
_PUNCT_RE = re.compile(r"[^\w؀-ۿ\s]", flags=re.UNICODE)
# Collapse runs of whitespace.
_WS_RE = re.compile(r"\s+")

# Honorifics + filler words that appear in declared names but not in
# civil records (or vice-versa). "ال" prefix is the Arabic definite
# article; we fold "المسلماني" -> "مسلماني" so it matches "مسلماني".
_AL_PREFIX_RE = re.compile(r"\bال")


def normalize(value) -> str:
    """Arabic-aware normalization for fuzzy field comparison.

    Order matters: NFKC first to fold compatibility forms, then digit
    map, then letter folds, then strip diacritics + zero-widths +
    tatweel + the definite article, then collapse whitespace.
    """
    if value is None:
        return ""
    s = str(value)
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_DIGIT_MAP)
    s = s.translate(_LETTER_MAP)
    s = _TASHKEEL_RE.sub("", s)
    s = _ZW_RE.sub("", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _AL_PREFIX_RE.sub("", s)
    s = _WS_RE.sub(" ", s)
    return s.strip().lower()


def _ratio(a: str, b: str) -> float:
    """Fuzzy ratio in [0, 1]. Token-set so reordered names match."""
    if not a or not b:
        return 0.0
    if fuzz is not None:
        return max(
            fuzz.token_set_ratio(a, b),
            fuzz.partial_ratio(a, b),
        ) / 100.0
    # rapidfuzz absent — fall back to difflib so the module still
    # imports in a stripped dev env. Quality is worse for Arabic.
    from difflib import SequenceMatcher
    return SequenceMatcher(None, a, b).ratio()


def compare_field(declared: str, extracted: str) -> dict:
    """Compare a single declared value against an extracted value."""
    d = normalize(declared)
    e = normalize(extracted)

    if not d and not e:
        return {"match": True, "similarity": 1.0, "status": "both_empty"}
    if d == e:
        return {"match": True, "similarity": 1.0, "status": "exact_match"}

    ratio = _ratio(d, e)

    if ratio >= MATCH_THRESHOLD:
        return {"match": True, "similarity": round(ratio, 4), "status": "close_match"}
    if ratio >= MISMATCH_THRESHOLD:
        return {"match": False, "similarity": round(ratio, 4), "status": "partial_match"}
    return {"match": False, "similarity": round(ratio, 4), "status": "mismatch"}


def _best_extracted(declared_value: str, ocr_keys: list[str], ocr_fields: dict[str, str]):
    """For multi-field declared values (full_name), try each candidate
    OCR field and keep the one with the highest similarity.

    Concatenated candidates: when comparing declared "محمد مسلماني"
    against OCR fields that split first-name and surname into
    full_name_ar + surname_ar, we also try the joined string so the
    full-name match doesn't depend on which OCR row Vision happened
    to land on.
    """
    best = (None, None, -1.0)

    # Single-field candidates. Track even ratio=0 so a present-but-
    # unrelated extracted value reports as a mismatch (the right
    # decision for the validator) instead of "not found in OCR".
    for ok in ocr_keys:
        v = ocr_fields.get(ok)
        if not v:
            continue
        r = _ratio(normalize(declared_value), normalize(v))
        if r > best[2]:
            best = (ok, v, r)

    # Try concatenations of (first_name, surname) when both exist
    fn = ocr_fields.get("full_name_ar") or ocr_fields.get("given_names")
    sn = ocr_fields.get("surname_ar") or ocr_fields.get("surname")
    if fn and sn:
        joined = f"{fn} {sn}"
        r = _ratio(normalize(declared_value), normalize(joined))
        if r > best[2]:
            best = ("full_name_ar+surname_ar", joined, r)

    if best[2] < 0:
        return (None, None, 0.0)
    return best  # (key, value, ratio)


def reconcile(
    declared_fields: dict[str, str],
    ocr_fields: dict[str, str],
) -> dict:
    """Field-by-field reconciliation between declared + extracted values.

    Output shape (kept stable for orchestrator / FE / audit consumers):

        {
            "field_results": {field: {match, similarity, status, declared, extracted}},
            "mismatch_flags": [...],
            "not_found_fields": [...],
            "integrity_score": float,
            "validation_result": "pass" | "need_info" | "fail",
            "total_fields": int,
            "matched_fields": int,
        }
    """
    field_results: dict[str, dict] = {}
    matches = 0
    total = 0

    for declared_key, declared_value in declared_fields.items():
        if not declared_value:
            continue
        if declared_key in SKIP_RECONCILIATION_FIELDS:
            # Citizen-typed metadata with no document analog — keeping it
            # in the loop would always score "not_found_in_ocr" and pull
            # integrity down on otherwise-clean cases. See constant doc.
            continue

        ocr_keys = FIELD_MAPPING.get(declared_key, [declared_key])
        chosen_key, extracted_value, best_ratio = _best_extracted(
            declared_value, ocr_keys, ocr_fields
        )

        if extracted_value is None:
            field_results[declared_key] = {
                "match": False,
                "similarity": 0.0,
                "status": "not_found_in_ocr",
                "declared": declared_value,
                "extracted": None,
            }
            total += 1
            continue

        # Re-derive match/status from the best ratio so the displayed
        # similarity matches what we used to pick the candidate.
        if best_ratio >= MATCH_THRESHOLD:
            status = "exact_match" if best_ratio == 1.0 else "close_match"
            match = True
        elif best_ratio >= MISMATCH_THRESHOLD:
            status, match = "partial_match", False
        else:
            status, match = "mismatch", False

        field_results[declared_key] = {
            "match": match,
            "similarity": round(best_ratio, 4),
            "status": status,
            "declared": declared_value,
            "extracted": extracted_value,
            "matched_against": chosen_key,
        }

        total += 1
        if match:
            matches += 1

    integrity_score = matches / total if total > 0 else 0.0

    mismatch_flags = [
        f for f, r in field_results.items()
        if not r["match"] and r["status"] != "not_found_in_ocr"
    ]
    not_found = [
        f for f, r in field_results.items() if r["status"] == "not_found_in_ocr"
    ]

    if integrity_score >= 0.9 and len(mismatch_flags) == 0:
        validation_result = "pass"
    elif len(mismatch_flags) >= 3 or integrity_score < 0.4:
        validation_result = "fail"
    else:
        validation_result = "need_info"

    return {
        "field_results": field_results,
        "mismatch_flags": mismatch_flags,
        "not_found_fields": not_found,
        "integrity_score": round(integrity_score, 4),
        "validation_result": validation_result,
        "total_fields": total,
        "matched_fields": matches,
    }
