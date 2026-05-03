"""LLM-backed structured-field extraction.

The LLM is the ONLY field extractor for every supported document
type. We send it BOTH the Google Vision OCR text *and* the original
image bytes — vision-capable models read the image directly and use
the OCR transcript as a redundant text channel — then ask for a
strict JSON object whose keys match the canonical field names
downstream code already uses.

Why no regex pass before this:
- Real Lebanese docs are Arabic-only or mixed-direction. Regex
  routinely captured the wrong cell when label/value pairs landed
  on different OCR lines (table cells in civil-registry extracts).
- Per-document-type regex was a maintenance tax that the LLM's
  per-doc schemas pay once and reuse across all flows.
- Cost: ~$0.005/call on gpt-4o-mini. ~5 docs/case for passport_new
  ≈ $0.025/case, an acceptable tradeoff for the accuracy gain.

MRZ stays parser-based (services/ocr/app/services/mrz_parser.py) —
ICAO 9303 is a fixed grammar with check digits, that's a parser job,
not text-pattern work. We additionally ask the LLM for `mrz_llm_*`
fields on bottom-half passport schemas as a sanity-check channel
(parser disagrees with LLM transcription → likely forgery / bad
capture → manual review).

Failure modes are intentionally non-fatal: any LLM error returns
an empty dict so the caller can proceed with quality gates and
classifier output even when the extractor is unavailable.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

from ..metrics import (
    OCR_LLM_CALLS, OCR_LLM_DURATION, OCR_LLM_FIELDS_EXTRACTED, OCR_LLM_TOKENS,
)
from . import langfuse_client

logger = logging.getLogger(__name__)


# Per-document-type schemas. Real Lebanese civil-status documents
# split the holder's name across separate cells (الاسم = first name,
# الشهرة = surname). We extract those as `first_name_ar` + `surname_ar`
# and let the OCR router synthesise `full_name_ar` from them. The
# orchestrator's reconciliation matches against the synthesised join.
_LEBANESE_ID_SHARED = {
    "first_name_ar": (
        "FIRST NAME ONLY of the document holder, in Arabic. Cell labelled الاسم. "
        "Example: محمد. Do NOT confuse with the mother's name (إسم الأم وشهرتها) "
        "or the father's name (اسم الأب)."
    ),
    "surname_ar":    "Surname (family name) in Arabic. Cell labelled الشهرة. Example: مسلماني.",
    "father_name":   "Father's first name in Arabic. Cell labelled اسم الأب. Example: علي.",
    "mother_name":   "Mother's first name + her family name. Cell labelled إسم الأم وشهرتها. Example: زهرة أيوب.",
    "date_of_birth": "Date of birth as YYYY-MM-DD. Convert from any printed format including Arabic numerals.",
    "place_of_birth": "Place of birth in Arabic. Cell labelled محل الولادة. Example: صور.",
    "gender":        "ذكر or أنثى. Cell labelled الجنس.",
    "id_number":     "Lebanese national-ID number; cell labelled رقم بطاقة الهوية. Digits only — strip dots, spaces, dashes.",
    "register_place": "Registry place + number from the row labelled محل ورقم القيد. Example: الشعيتية 53.",
    "district":      "Administrative district (قضاء) in Arabic. Cell labelled القضاء. Example: صور.",
    "religious_sect": "Religious sect (مذهب) in Arabic. Cell labelled المذهب. Example: شيعي / ماروني / سني / درزي.",
    "marital_status": "Marital status in Arabic. Cell labelled الوضع العائلي. Example: أعزب / متزوج / مطلق / أرمل.",
}

_LEBANESE_PASSPORT = {
    "surname":       "Surname in Latin script as printed on the data page. Example: AYOUB.",
    "given_names":   "Given names in Latin script. Example: ZAHRA.",
    "surname_ar":    "Surname in Arabic if printed. Example: أيوب.",
    "first_name_ar": "Given name in Arabic if printed. Example: زهرة.",
    "father_name":   "Father's name in Arabic if printed. Example: سعيد.",
    "mother_name":   "Mother's full name in Arabic if printed. Example: زينب قليط.",
    "passport_number": "Passport number from the data page. Lebanese biometric passports start with LR. Example: LR3044513.",
    "nationality":   "Three-letter ISO code (LBN for Lebanese). Example: LBN.",
    "date_of_birth": "Date of birth as YYYY-MM-DD.",
    "place_of_birth": "Place of birth as printed (Latin or Arabic). Example: BOUKIE.",
    "sex":           "M or F.",
    "date_of_issue": "Issuance date as YYYY-MM-DD.",
    "date_of_expiry": "Expiry date as YYYY-MM-DD.",
    "registry_place": "Registry place + number where present. Example: 53.",
}

# Top half of the passport data page: printed photo, surname, given
# names, dates, nationality. NO MRZ here — that lives on the bottom
# half and is parsed by the ICAO grammar (mrz_parser.py), not by the
# LLM. We list date_of_birth + sex twice (top *and* bottom schemas)
# because they appear printed on the visual top AND encoded in the
# MRZ — having both lets the merge step cross-check.
_LEBANESE_PASSPORT_TOP = {
    "surname":       "Surname in Latin script as printed on the data page. Example: AYOUB.",
    "given_names":   "Given names in Latin script. Example: ZAHRA.",
    "surname_ar":    "Surname in Arabic if printed. Example: أيوب.",
    "first_name_ar": "Given name in Arabic if printed. Example: زهرة.",
    "father_name":   "Father's name in Arabic if printed. Example: سعيد.",
    "mother_name":   "Mother's full name in Arabic if printed. Example: زينب قليط.",
    "passport_number": "Passport number from the data page. Lebanese biometric passports start with LR. Example: LR3044513.",
    "nationality":   "Three-letter ISO code (LBN for Lebanese). Example: LBN.",
    "date_of_birth": "Date of birth as YYYY-MM-DD.",
    "place_of_birth": "Place of birth as printed (Latin or Arabic). Example: BOUKIE.",
    "sex":           "M or F.",
    "date_of_issue": "Issuance date as YYYY-MM-DD.",
    "date_of_expiry": "Expiry date as YYYY-MM-DD.",
    "registry_place": "Registry place + number where present. Example: 53.",
}

# Bottom half: the MRZ block plus any signature / authority text.
# The ICAO grammar parser is authoritative for MRZ fields; the LLM
# transcription is captured as a sanity-check signal so reconciliation
# can spot when the two disagree (likely indicating a forgery or a
# bad capture). Field names are prefixed `mrz_llm_` so the merge step
# doesn't clobber the parser-derived values keyed `mrz_*`.
_LEBANESE_PASSPORT_BOTTOM = {
    "mrz_line_1": "First line of the MRZ exactly as printed (44 chars including '<' fillers).",
    "mrz_line_2": "Second line of the MRZ exactly as printed (44 chars including '<' fillers).",
    "mrz_llm_passport_number": "Passport number transcribed from the MRZ (positions 1-9 of line 2).",
    "mrz_llm_surname": "Surname transcribed from line 1 of the MRZ (before the '<<').",
    "mrz_llm_given_names": "Given names transcribed from line 1 of the MRZ (after the '<<').",
    "mrz_llm_date_of_birth": "Date of birth from MRZ as YYYY-MM-DD (positions 14-19 of line 2, YYMMDD).",
    "mrz_llm_date_of_expiry": "Date of expiry from MRZ as YYYY-MM-DD (positions 22-27 of line 2, YYMMDD).",
    "mrz_llm_nationality": "Three-letter ISO nationality from MRZ (positions 11-13 of line 2). Example: LBN.",
    "mrz_llm_sex": "M or F from the MRZ (position 21 of line 2).",
    "issuing_authority": "Issuing authority text printed on the bottom half if present.",
}

_SCHEMAS: dict[str, dict[str, str]] = {
    "civil_registry_extract": _LEBANESE_ID_SHARED,
    "national_id_front":      _LEBANESE_ID_SHARED,
    "old_id_front":           _LEBANESE_ID_SHARED,
    # Back face of either ID generation: issuance date, register
    # locale, district, sect, marital status, plus the ID number
    # (printed on both faces). Holder name is NOT on the back.
    "national_id_back": {
        "id_number":      "Lebanese national-ID number, digits only.",
        "issue_date":     "Date of issue as YYYY-MM-DD. Cell labelled تاريخ الإصدار.",
        "expiry_date":    "Date of expiry as YYYY-MM-DD if printed.",
        "register_place": "Registration locale (محلة أو القرية / محل السجل).",
        "district":       "Administrative district (قضاء).",
        "religious_sect": "Religious sect (مذهب) in Arabic.",
        "marital_status": "Marital status (الوضع العائلي).",
    },
    "old_id_back": {
        "id_number":      "Old-format ID number, digits only.",
        "issue_date":     "Date of issue as YYYY-MM-DD if printed.",
        "expiry_date":    "Date of expiry as YYYY-MM-DD if printed.",
        "register_place": "Place of registration.",
    },
    "passport_data_page":     _LEBANESE_PASSPORT,
    "old_passport_data_page": _LEBANESE_PASSPORT,
    "passport_data_page_top":         _LEBANESE_PASSPORT_TOP,
    "passport_data_page_bottom":      _LEBANESE_PASSPORT_BOTTOM,
    "old_passport_data_page_top":     _LEBANESE_PASSPORT_TOP,
    "old_passport_data_page_bottom":  _LEBANESE_PASSPORT_BOTTOM,
    "birth_certificate": {
        "first_name_ar": "First name of the registered person in Arabic.",
        "surname_ar":    "Surname in Arabic.",
        "father_name":   "Father's name in Arabic.",
        "mother_name":   "Mother's full name in Arabic.",
        "date_of_birth": "Date of birth as YYYY-MM-DD.",
        "place_of_birth": "Place of birth in Arabic.",
        "register_number": "Registry / record number from this birth certificate, digits only.",
    },
}

# Generic fallback schema. The LLM is now unconditional — every OCR'd
# doc gets a vision-pass even when we don't have a hand-tuned schema
# for it. The fallback keys are the lowest-common-denominator fields
# we want regardless of doc class; the model returns nulls for any
# that aren't on the page and `_normalise` drops them.
_GENERIC_FALLBACK = {
    "full_name":     "Full name of the document holder if printed.",
    "first_name_ar": "First name in Arabic if printed.",
    "surname_ar":    "Surname in Arabic if printed.",
    "id_number":     "Any document/registry/ID number printed on the page, digits only.",
    "date_of_birth": "Date of birth as YYYY-MM-DD if printed.",
    "issue_date":    "Issue / registration date as YYYY-MM-DD if printed.",
    "expiry_date":   "Expiry date as YYYY-MM-DD if printed.",
}


def supports(document_type: str) -> bool:
    """True if the LLM extractor has a hand-tuned schema for this doc type.

    The router now calls the LLM unconditionally — unsupported doc types
    fall through to `_GENERIC_FALLBACK` rather than being skipped — so
    callers should treat this as an informational tag rather than a gate.
    """
    return document_type in _SCHEMAS


def _schema_for(document_type: str) -> dict[str, str]:
    """Return the per-doc schema or the generic fallback."""
    return _SCHEMAS.get(document_type, _GENERIC_FALLBACK)


# Code-side fallback for the field-extractor system prompt. This is the
# canonical version — Langfuse, if configured, can override it without
# a code change by editing the prompt with the same name and promoting
# a new "production" label. Keep this string in sync with whatever's
# in Langfuse so unconfigured deploys don't drift.
_FIELD_EXTRACTOR_SYSTEM_FALLBACK = (
    "You extract structured fields from photographed Lebanese civil-status "
    "documents. The document image plus the raw OCR text are both attached. "
    "Return a single JSON object whose keys are the requested field names "
    "and whose values are the extracted strings (Arabic preserved verbatim). "
    "Use null for any field genuinely not present or unreadable. "
    "Do not invent values, do not translate Arabic to English, and do not "
    "include any keys other than those listed."
)


def _build_messages(
    document_type: str, ocr_text: str, image_bytes: bytes,
) -> tuple[list[dict], "langfuse_client.ManagedPrompt"]:
    """Build the chat-completion messages + return the resolved prompt.

    Returning the ManagedPrompt alongside the messages lets the caller
    link its Langfuse generation observation back to the prompt
    version actually used (so prompt edits in Langfuse roll forward
    into eval reports).
    """
    schema = _schema_for(document_type)
    fields_doc = "\n".join(f"  - {k}: {v}" for k, v in schema.items())

    managed = langfuse_client.get_prompt(
        langfuse_client.PROMPT_NAME_FIELD_EXTRACTOR,
        fallback=_FIELD_EXTRACTOR_SYSTEM_FALLBACK,
    )
    system = managed.text
    user_text = (
        f"Document type: {document_type}\n\n"
        f"Required fields:\n{fields_doc}\n\n"
        f"Raw OCR text (line order may not match visual layout):\n{ocr_text}\n\n"
        "Return JSON now."
    )

    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    messages = [
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
    return messages, managed


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
    langfuse_trace: Any | None = None,
) -> tuple[dict[str, str], dict[str, Any]]:
    """Run the LLM extractor against this document.

    Returns (fields, trace).
      - fields: {field_name: string_value} — empty on any failure
        path so the caller can fall through to regex output.
      - trace: structured record of what we sent + got back (or why
        the call was skipped). Includes prompt text, raw response,
        token usage, model name, elapsed time, and outcome. Image
        bytes are intentionally NOT included — the doc has its own
        hash captured elsewhere and we don't want audit_logs to
        balloon. The caller is responsible for persisting the trace
        (typically forwarded to the gateway and written to
        audit_logs keyed by case_id).
    """
    model_name = model or "gpt-4o-mini"
    trace: dict[str, Any] = {
        "model": model_name,
        "document_type": document_type,
        "outcome": None,
        # Tagged so traces can be filtered by whether the doc type had a
        # hand-tuned schema or was extracted via the generic fallback.
        "schema_kind": "tuned" if supports(document_type) else "generic",
    }

    # Mock-mode shortcut. Now that the LLM is the ONLY field
    # extractor, mock-mode E2E tests must not call OpenAI — they
    # need a deterministic fixture that returns canonical fields
    # for each doc type so the orchestrator pipeline runs through
    # to a final routing decision without an API key.
    try:
        from ..config import get_settings
        if get_settings().mock_mode:
            from .mock_llm import MOCK_LLM_FIELDS
            fields = MOCK_LLM_FIELDS.get(document_type, {}).copy()
            OCR_LLM_CALLS.labels(
                document_type=document_type, model=model_name, outcome="mock",
            ).inc()
            trace.update({
                "outcome": "mock",
                "extracted_fields": fields,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "elapsed_ms": 0,
            })
            return fields, trace
    except Exception:  # noqa: BLE001
        # Mock infrastructure failure must never block the real path.
        pass

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        logger.warning("ai_extractor: OPENAI_API_KEY not set, skipping")
        OCR_LLM_CALLS.labels(
            document_type=document_type, model=model_name, outcome="skipped_no_key",
        ).inc()
        trace["outcome"] = "skipped_no_key"
        return {}, trace

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("ai_extractor: openai package not installed, skipping")
        OCR_LLM_CALLS.labels(
            document_type=document_type, model=model_name, outcome="skipped_no_package",
        ).inc()
        trace["outcome"] = "skipped_no_package"
        return {}, trace

    client = OpenAI(api_key=key)
    messages, managed_prompt = _build_messages(document_type, ocr_text, image_bytes)
    schema_keys = set(_schema_for(document_type).keys())
    trace["prompt_version"] = managed_prompt.version
    trace["prompt_source"] = managed_prompt.source

    # Capture prompt for the trace BEFORE the API call so a network
    # error still yields a usable record. We strip the base64 image
    # from the user message to keep audit_logs small — the OCR text
    # alone is enough to debug what the model saw.
    system_prompt = next((m["content"] for m in messages if m["role"] == "system"), "")
    user_text = ""
    for m in messages:
        if m["role"] != "user":
            continue
        content = m["content"]
        if isinstance(content, list):
            for part in content:
                if part.get("type") == "text":
                    user_text = part.get("text", "")
                    break
        else:
            user_text = content
        break
    trace["prompt"] = {"system": system_prompt, "user": user_text}

    started = time.perf_counter()
    try:
        # response_format=json_object forces the model to return a
        # single parseable JSON object — saves us a try/except on
        # malformed-text outputs.
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=800,
        )
        elapsed_s = time.perf_counter() - started
        content = resp.choices[0].message.content or "{}"
        raw = json.loads(content)
        fields = _normalise(raw, schema_keys)

        OCR_LLM_CALLS.labels(
            document_type=document_type, model=model_name, outcome="success",
        ).inc()
        OCR_LLM_DURATION.labels(
            document_type=document_type, model=model_name,
        ).observe(elapsed_s)
        OCR_LLM_FIELDS_EXTRACTED.labels(document_type=document_type).observe(len(fields))

        prompt_tokens = 0
        completion_tokens = 0
        usage = getattr(resp, "usage", None)
        if usage is not None:
            # Attribute names differ across openai-python versions;
            # tolerate both camelCase and snake_case.
            prompt_tokens = getattr(usage, "prompt_tokens", None) or getattr(usage, "promptTokens", 0) or 0
            completion_tokens = getattr(usage, "completion_tokens", None) or getattr(usage, "completionTokens", 0) or 0
            if prompt_tokens:
                OCR_LLM_TOKENS.labels(model=model_name, kind="prompt").inc(prompt_tokens)
            if completion_tokens:
                OCR_LLM_TOKENS.labels(model=model_name, kind="completion").inc(completion_tokens)

        trace.update({
            "outcome": "success",
            "raw_response": content,
            "extracted_fields": fields,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "elapsed_ms": int(elapsed_s * 1000),
        })

        logger.info(
            "ai_extractor: %s extracted %d fields in %dms",
            document_type, len(fields), int(elapsed_s * 1000),
        )
        langfuse_client.log_generation(
            langfuse_trace,
            name=f"field-extractor.{document_type}",
            model=model_name,
            messages=messages,
            response_text=content,
            parsed_output=fields,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=int(elapsed_s * 1000),
            outcome="success",
            prompt_obj=managed_prompt.langfuse_obj,
            metadata={
                "document_type": document_type,
                "fields_extracted": len(fields),
                "prompt_source": managed_prompt.source,
            },
        )
        return fields, trace
    except Exception as exc:  # noqa: BLE001
        # Defensive: any LLM/network/parse error should not crash
        # the OCR pipeline. Log and return empty so the caller
        # falls through to whatever regex produced.
        OCR_LLM_CALLS.labels(
            document_type=document_type, model=model_name, outcome="error",
        ).inc()
        OCR_LLM_DURATION.labels(
            document_type=document_type, model=model_name,
        ).observe(time.perf_counter() - started)
        logger.warning("ai_extractor: %s failed: %s", document_type, exc)
        trace.update({
            "outcome": "error",
            "error": str(exc),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        })
        langfuse_client.log_generation(
            langfuse_trace,
            name=f"field-extractor.{document_type}",
            model=model_name,
            messages=messages,
            response_text=None,
            parsed_output=None,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            outcome="error",
            error=str(exc),
            prompt_obj=managed_prompt.langfuse_obj,
            metadata={"document_type": document_type, "prompt_source": managed_prompt.source},
        )
        return {}, trace
