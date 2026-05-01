"""LLM-backed structured-field extraction.

Used as a *fallback* when the regex extractor in
`field_extractor.py` can't parse a doc — primarily Lebanese civil
registry extracts (بيان قيد إفرادي), which are 3-column tables
with labels and values in different cells. Google Vision returns
table cells line-by-line in geographic order, which is enough for
a vision-language model to reason about but breaks the
"label[:\\s]+value" regex shape entirely.

The LLM is sent BOTH the OCR text *and* the original image
bytes (vision-capable models read the image directly), then asked
to return a strict JSON object whose keys match the canonical
field names downstream code already uses. That lets the router
merge LLM results into the same `fields` dict regex produced
without changing any consumer.

Cost: ~$0.005 per civil-registry extract on gpt-4o-mini. We only
call the LLM when regex returns < `OCR_LLM_FALLBACK_MIN_FIELDS`,
so passport MRZ flows (which regex handles cheaply) never pay it.

Failure modes are intentionally non-fatal: any LLM error returns
an empty dict and the caller proceeds with whatever regex found.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)


# Per-document-type schemas. Keys here MUST match the canonical
# field names produced by the regex extractor so the merged output
# stays consistent for downstream code (orchestrator, reconciler,
# UI).
_SCHEMAS: dict[str, dict[str, str]] = {
    "civil_registry_extract": {
        # Be explicit about WHICH cell to read — earlier responses
        # confused the mother-name row (إسم الأم وشهرتها) with the
        # first-name row (الإسم) because both appear near the top.
        "full_name_ar": (
            "FIRST NAME ONLY of the document holder, in Arabic. "
            "Read the value cell to the LEFT of the label الإسم. "
            "Example: محمد. DO NOT confuse with the mother's name "
            "(which is on the row labelled إسم الأم وشهرتها) or the "
            "father's name (إسم الأب)."
        ),
        "surname_ar":   "Surname (family name) of the document holder, in Arabic. Row labelled الشهرة. Example: مسلماني.",
        "father_name":  "Father's first name in Arabic. Row labelled إسم الأب. Example: علي.",
        "mother_name":  "Mother's first name + her family name. Row labelled إسم الأم وشهرتها. Example: زهرة أيوب.",
        "date_of_birth": "Date of birth as YYYY-MM-DD. Convert from any printed format including Arabic numerals.",
        "place_of_birth": "Place of birth in Arabic. Row labelled محل الولادة.",
        "gender":       "ذكر or أنثى. Row labelled الجنس.",
        "id_number":    "Lebanese ID-card number; row labelled رقم بطاقة الهوية. Return digits only, strip dots and spaces.",
        "register_place": "Registry place + number from the row labelled محل ورقم القيد. Example: الشعيتية 53.",
        "religious_sect": "Religious sect in Arabic. Row labelled المذهب. Example: شيعي / ماروني / سني.",
        "marital_status": "Marital status in Arabic. Row labelled الوضع العائلي. Example: أعزب / متزوج.",
        "district":     "Administrative district (قضاء), in Arabic.",
    },
    "national_id_front": {
        "full_name_ar": "Full name in Arabic.",
        "full_name_en": "Full name in Latin script if printed.",
        "father_name":  "Father's name in Arabic.",
        "mother_name":  "Mother's name in Arabic.",
        "date_of_birth": "Date of birth as YYYY-MM-DD.",
        "place_of_birth": "Place of birth in Arabic.",
        "gender":       "ذكر or أنثى.",
        "id_number":    "Lebanese national ID number, digits only.",
        "register_place": "Place of registration.",
    },
    "national_id_back": {
        "id_number":    "ID number, digits only.",
        "issue_date":   "Date of issue, YYYY-MM-DD.",
        "expiry_date":  "Date of expiry, YYYY-MM-DD.",
        "register_place": "Place of registration.",
    },
    "old_id_front": {
        "full_name_ar": "Full name in Arabic.",
        "full_name_en": "Full name in Latin script if printed.",
        "father_name":  "Father's name in Arabic.",
        "mother_name":  "Mother's name in Arabic.",
        "date_of_birth": "Date of birth as YYYY-MM-DD.",
        "place_of_birth": "Place of birth in Arabic.",
        "gender":       "ذكر or أنثى.",
        "id_number":    "Lebanese national ID number, digits only.",
        "register_place": "Place of registration.",
    },
    "old_id_back": {
        "id_number":    "ID number, digits only.",
        "issue_date":   "Date of issue, YYYY-MM-DD.",
        "expiry_date":  "Date of expiry, YYYY-MM-DD.",
        "register_place": "Place of registration.",
    },
}


def supports(document_type: str) -> bool:
    """True if the LLM extractor has a schema for this doc type."""
    return document_type in _SCHEMAS


def _build_messages(document_type: str, ocr_text: str, image_bytes: bytes) -> list[dict]:
    schema = _SCHEMAS[document_type]
    fields_doc = "\n".join(f"  - {k}: {v}" for k, v in schema.items())

    system = (
        "You extract structured fields from photographed Lebanese civil-status "
        "documents. The document image plus the raw OCR text are both attached. "
        "Return a single JSON object whose keys are the requested field names "
        "and whose values are the extracted strings (Arabic preserved verbatim). "
        "Use null for any field genuinely not present or unreadable. "
        "Do not invent values, do not translate Arabic to English, and do not "
        "include any keys other than those listed."
    )
    user_text = (
        f"Document type: {document_type}\n\n"
        f"Required fields:\n{fields_doc}\n\n"
        f"Raw OCR text (line order may not match visual layout):\n{ocr_text}\n\n"
        "Return JSON now."
    )

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                },
            ],
        },
    ]


def _normalise(raw: dict[str, Any], schema_keys: set[str]) -> dict[str, str]:
    """Drop nulls + non-schema keys, coerce values to strings."""
    out: dict[str, str] = {}
    for k, v in (raw or {}).items():
        if k not in schema_keys:
            continue
        if v is None:
            continue
        s = str(v).strip()
        if s and s.lower() not in ("null", "none", "n/a"):
            out[k] = s
    return out


def extract_with_llm(
    document_type: str,
    ocr_text: str,
    image_bytes: bytes,
    *,
    model: str | None = None,
    api_key: str | None = None,
) -> dict[str, str]:
    """Run the LLM extractor against this document.

    Returns a dict of {field_name: string_value}. Empty on any
    failure path — caller should treat empty as "LLM didn't help"
    rather than raising.
    """
    if not supports(document_type):
        return {}

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        logger.warning("ai_extractor: OPENAI_API_KEY not set, skipping")
        return {}

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("ai_extractor: openai package not installed, skipping")
        return {}

    client = OpenAI(api_key=key)
    messages = _build_messages(document_type, ocr_text, image_bytes)
    schema_keys = set(_SCHEMAS[document_type].keys())

    started = time.perf_counter()
    try:
        # response_format=json_object forces the model to return a
        # single parseable JSON object — saves us a try/except on
        # malformed-text outputs.
        resp = client.chat.completions.create(
            model=model or "gpt-4o-mini",
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=800,
        )
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        content = resp.choices[0].message.content or "{}"
        raw = json.loads(content)
        fields = _normalise(raw, schema_keys)
        logger.info(
            "ai_extractor: %s extracted %d fields in %dms",
            document_type, len(fields), elapsed_ms,
        )
        return fields
    except Exception as exc:  # noqa: BLE001
        # Defensive: any LLM/network/parse error should not crash
        # the OCR pipeline. Log and return empty so the caller
        # falls through to whatever regex produced.
        logger.warning("ai_extractor: %s failed: %s", document_type, exc)
        return {}
