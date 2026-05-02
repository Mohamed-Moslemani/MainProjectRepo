"""Document-type + authenticity classifier.

The OCR field extractor trusts the citizen-supplied `document_type`
label and tries to extract whichever schema matches that label. That
works fine for a cooperating citizen, but it gives no defence against:

  - Wrong-document uploads. Citizen labels a power bill as
    `passport_data_page`. Field extraction returns mostly nulls; the
    case may still pass the missing-fields gate via the LLM's
    hallucinated guesses or limp into manual review with no signal
    saying "this isn't even a passport".

  - Casual forgery. Citizen photoshops a passport-shaped image with
    altered names. The OCR / extractor reads the altered fields
    verbatim and the case proceeds as if the document were genuine.

This module runs a vision-LLM classification pass BEFORE field
extraction. For each upload it returns:

  - `matches_expected_type`: did the image look like the document
    type the citizen claimed?
  - `detected_type`: what the model thinks the image actually is.
  - `looks_authentic`: does the image's structure (fonts, layout,
    emblems, holograms-as-photographed, MRZ presence on passports,
    3-column civil-registry table layout, …) match what a real
    Lebanese government document of this type looks like?
  - `confidence`: model's self-reported confidence 0..1.
  - `reasons`: short bullets the audit log + retake banner can show.

We are deliberately conservative about claiming "authenticity":
without forensic features (chip, hologram, UV ink) a vision model
can only catch CASUAL forgery and wrong-document uploads. That's
still strictly better than the current state, which catches
neither.

Mock mode returns a deterministic happy classification so the E2E
suite stays offline.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any

from ..metrics import (
    OCR_CLASSIFIER_CALLS,
    OCR_CLASSIFIER_DURATION,
    OCR_CLASSIFIER_REJECTED,
)
from . import langfuse_client

logger = logging.getLogger(__name__)


# Visible features that distinguish each Lebanese document type.
# Sent to the model as part of the prompt so the classifier has a
# crisp checklist of what to look for. Wrong values here directly
# cause false rejects, so each entry should describe features that
# are visually unambiguous on a normal phone-camera photo.
_DOC_SIGNATURES: dict[str, str] = {
    "national_id_front": (
        "Lebanese national ID card, front face. Cedar-tree emblem at top, "
        "the header الجمهورية اللبنانية / République Libanaise, holder photo "
        "on the right, fields الاسم (first name), الشهرة (surname), اسم الأب "
        "(father), اسم الأم وشهرتها (mother), تاريخ الولادة (date of birth), "
        "محل الولادة (place of birth), and a barcode/QR. Card-shaped (ID-1 "
        "credit-card aspect ratio). Modern biometric variant has a chip on "
        "the front."
    ),
    "national_id_back": (
        "Lebanese national ID card, back face. Cedar emblem, ID number "
        "(رقم بطاقة الهوية), issue date (تاريخ الإصدار), registry place "
        "(محل ورقم القيد), district (القضاء), religious sect (المذهب), "
        "marital status (الوضع العائلي), holder signature strip, and "
        "machine-readable line on the bottom. Card-shaped."
    ),
    "old_id_front": (
        "Older-style Lebanese ID card, front face — pre-biometric, "
        "softer cardstock, holder photo, similar Arabic field labels "
        "(الاسم, الشهرة, اسم الأب, اسم الأم, تاريخ الولادة)."
    ),
    "old_id_back": (
        "Older-style Lebanese ID card, back face. Issuance details, "
        "registry locale, district, sect, marital status. Pre-biometric "
        "cardstock without machine-readable line."
    ),
    "passport_data_page": (
        "Lebanese biometric passport data page. ICAO 9303 layout: holder "
        "portrait top-left, machine-readable zone (TWO lines of "
        "OCR-B characters with chevrons '<') along the bottom, fields "
        "Type (P), Country code (LBN), Passport No (starts with LR…), "
        "Surname/Given Names in Latin and Arabic, Nationality (LEBANESE "
        "/ لبناني), Date of birth, Sex, Place of birth, Date of issue, "
        "Date of expiry. Embedded chip symbol on the cover but the "
        "data page itself is paper. Cedar emblem above the page header."
    ),
    "old_passport_data_page": (
        "Older non-biometric Lebanese passport. Typed data page, no "
        "or older-style MRZ, may lack the chip symbol. Same Lebanese "
        "passport visual identity (cedar, République Libanaise header)."
    ),
    "civil_registry_extract": (
        "Lebanese civil-registry individual extract (بيان قيد إفرادي). "
        "Three-column tabular layout: label / value / sometimes a "
        "secondary column. Header reads الجمهورية اللبنانية / وزارة "
        "الداخلية والبلديات / المديرية العامة للأحوال الشخصية / بيان قيد "
        "إفرادي. Rows include الاسم, الشهرة, اسم الأب, اسم الأم, تاريخ "
        "الولادة, محل الولادة, الجنس, القضاء, المذهب, الوضع العائلي, "
        "محل ورقم القيد. Bottom of page has issuance metadata + "
        "official stamp."
    ),
    "selfie": (
        "Live selfie of the applicant — single human face, frontal, "
        "visible facial features. Should NOT be a photo of an ID/document."
    ),
    "liveness_capture": (
        "Liveness-challenge frame from AWS Rekognition Face Liveness "
        "or equivalent. Single face captured against the on-screen "
        "challenge UI."
    ),
    "police_report": (
        "Official Lebanese police / Internal Security Forces report. "
        "Heading قوى الأمن الداخلي or محضر شرطة, narrative text, "
        "officer signature, station stamp."
    ),
    "court_ruling": (
        "Lebanese court ruling / judicial document. Heading naming "
        "the court (محكمة), case number, ruling text, judge signature, "
        "court seal."
    ),
    "damaged_passport": (
        "A Lebanese passport (data page or cover) that has been "
        "physically damaged — water damage, tears, burnt edges, "
        "ink smearing. Visibly unfit for travel use."
    ),
    "additional_identity_proof": (
        "Any supplementary government-issued identity proof — driver's "
        "licence, university ID, employer ID, etc. Should still display "
        "holder name, photo, and an issuing authority."
    ),
}


# Doc types we can classify. Anything not in here gets a pass-through
# (the OCR pipeline trusts the citizen's label). Keep this set in sync
# with _DOC_SIGNATURES — `supports()` reads from there.


@dataclass
class ClassificationResult:
    matches_expected_type: bool
    detected_type: str | None
    confidence: float
    looks_authentic: bool
    reasons: list[str] = field(default_factory=list)
    outcome: str = "success"  # success, error, skipped_no_key, skipped_no_package, mock, skipped_unsupported

    def to_dict(self) -> dict:
        return {
            "matches_expected_type": self.matches_expected_type,
            "detected_type": self.detected_type,
            "confidence": round(self.confidence, 4),
            "looks_authentic": self.looks_authentic,
            "reasons": self.reasons,
            "outcome": self.outcome,
        }


def supports(document_type: str) -> bool:
    return document_type in _DOC_SIGNATURES


# Code-side fallback for the classifier system prompt — Langfuse can
# override this at runtime by editing the prompt with the same name.
_DOC_CLASSIFIER_SYSTEM_FALLBACK = (
    "You are a forensic document examiner reviewing a photograph "
    "uploaded to a Lebanese government online-application portal. "
    "Your job is to verify that the photographed object is the type "
    "of document the applicant claims, and that it has the visual "
    "structure of a genuine Lebanese government document of that "
    "type. You are NOT performing forensic authentication — you "
    "have no access to chips, holograms, or UV features. You ARE "
    "checking for: wrong-document uploads, obvious forgeries with "
    "mismatched fonts/layout, photos of screens, photoshopped "
    "fields, and documents from the wrong country.\n\n"
    "IMPORTANT: the citizen portal is Arabic-first. The `reasons` "
    "array MUST be written in clear, plain Arabic (اللغة العربية) "
    "— not English, not transliterated. The other JSON keys / "
    "boolean values stay in English. Use Arabic punctuation for "
    "Arabic text (use «» or no quotes; avoid English quotation marks)."
)


def _build_messages(
    expected_type: str, image_bytes: bytes,
) -> tuple[list[dict], "langfuse_client.ManagedPrompt"]:
    expected_signature = _DOC_SIGNATURES[expected_type]
    known_types = ", ".join(sorted(_DOC_SIGNATURES.keys()))

    managed = langfuse_client.get_prompt(
        langfuse_client.PROMPT_NAME_DOC_CLASSIFIER,
        fallback=_DOC_CLASSIFIER_SYSTEM_FALLBACK,
    )
    system = managed.text
    user_text = (
        f"Expected document type: {expected_type}\n"
        f"What that should look like:\n{expected_signature}\n\n"
        f"Known document types: {known_types}\n\n"
        "Examine the attached image. Return a JSON object with these keys:\n"
        '  - "matches_expected_type": boolean. true if the image is the type '
        "the applicant claimed.\n"
        '  - "detected_type": one of the known document types listed above, '
        "or null if you cannot identify it.\n"
        '  - "confidence": float 0..1 — your overall confidence in this '
        "verdict.\n"
        '  - "looks_authentic": boolean. false if you see obvious signs of '
        "forgery, screen photographs, mismatched fonts, photoshopped fields, "
        "or wrong-country documents. true otherwise (including when you can't "
        "tell either way — we explicitly do not fail closed on inability to "
        "verify, only on positive evidence of a problem).\n"
        '  - "reasons": array of short ARABIC strings (اللغة العربية) naming '
        "concrete observations that drove the verdict — examples: "
        '"لا تتوفر منطقة قراءة آلية MRZ على صفحة الجواز", "الصورة هي '
        'لقطة شاشة من تطبيق وليست مستنداً", "شعار الأرز غير موجود". '
        "Keep each entry under 120 characters. Return at most 4. "
        "Do NOT use English in `reasons`.\n\n"
        "Be conservative: do NOT flag inauthentic just because the image is "
        "low-resolution, blurry, or partially cropped — those are quality "
        "issues handled separately. Only flag if you see a positive signal "
        "that the upload is wrong-document or visibly forged."
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


def _coerce(raw: dict[str, Any], expected_type: str) -> ClassificationResult:
    matches = bool(raw.get("matches_expected_type", False))
    detected = raw.get("detected_type")
    if detected is not None:
        detected = str(detected).strip() or None
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    looks_authentic = bool(raw.get("looks_authentic", True))
    reasons_raw = raw.get("reasons") or []
    if isinstance(reasons_raw, str):
        reasons_raw = [reasons_raw]
    reasons = [str(r).strip()[:120] for r in reasons_raw if str(r).strip()][:4]

    return ClassificationResult(
        matches_expected_type=matches,
        detected_type=detected,
        confidence=confidence,
        looks_authentic=looks_authentic,
        reasons=reasons,
    )


def classify(
    expected_type: str,
    image_bytes: bytes,
    *,
    model: str | None = None,
    api_key: str | None = None,
    langfuse_trace: Any | None = None,
) -> tuple[ClassificationResult, dict[str, Any]]:
    """Return (result, trace).

    `trace` mirrors the structure used by ai_extractor — outcome,
    prompt, raw_response, token usage, elapsed_ms — so the gateway
    can persist it alongside the field-extraction trace under a
    single audit_logs entry per document.
    """
    model_name = model or "gpt-4o-mini"
    trace: dict[str, Any] = {
        "model": model_name,
        "expected_type": expected_type,
        "outcome": None,
    }

    if not supports(expected_type):
        OCR_CLASSIFIER_CALLS.labels(
            document_type=expected_type, model=model_name, outcome="skipped_unsupported",
        ).inc()
        trace["outcome"] = "skipped_unsupported"
        # Pass-through: we don't know what this type should look like,
        # so don't block the pipeline on it.
        return ClassificationResult(
            matches_expected_type=True,
            detected_type=None,
            confidence=0.0,
            looks_authentic=True,
            outcome="skipped_unsupported",
        ), trace

    # Mock-mode shortcut. Match the field-extractor's mock behaviour
    # — return a confident, happy verdict so E2E tests pass without
    # an API key. Tests that need to exercise the rejection path do
    # so by passing an explicit `force_reject` flag in declared_fields
    # (handled in the OCR router).
    try:
        from ..config import get_settings
        if get_settings().mock_mode:
            OCR_CLASSIFIER_CALLS.labels(
                document_type=expected_type, model=model_name, outcome="mock",
            ).inc()
            result = ClassificationResult(
                matches_expected_type=True,
                detected_type=expected_type,
                confidence=0.95,
                looks_authentic=True,
                reasons=["mock-mode classification"],
                outcome="mock",
            )
            trace.update({
                "outcome": "mock",
                "result": result.to_dict(),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "elapsed_ms": 0,
            })
            return result, trace
    except Exception:  # noqa: BLE001
        pass

    key = api_key or os.getenv("OPENAI_API_KEY")
    if not key:
        OCR_CLASSIFIER_CALLS.labels(
            document_type=expected_type, model=model_name, outcome="skipped_no_key",
        ).inc()
        trace["outcome"] = "skipped_no_key"
        # Without the LLM we cannot classify. Fail-OPEN: the pipeline
        # has multiple downstream signals (field extraction, registry
        # cross-check, cross-doc coherence) that catch the same fraud
        # patterns. Failing closed here would lock out every prod
        # deploy that hasn't wired OPENAI_API_KEY yet.
        return ClassificationResult(
            matches_expected_type=True,
            detected_type=None,
            confidence=0.0,
            looks_authentic=True,
            outcome="skipped_no_key",
        ), trace

    try:
        from openai import OpenAI
    except ImportError:
        OCR_CLASSIFIER_CALLS.labels(
            document_type=expected_type, model=model_name, outcome="skipped_no_package",
        ).inc()
        trace["outcome"] = "skipped_no_package"
        return ClassificationResult(
            matches_expected_type=True,
            detected_type=None,
            confidence=0.0,
            looks_authentic=True,
            outcome="skipped_no_package",
        ), trace

    messages, managed_prompt = _build_messages(expected_type, image_bytes)
    trace["prompt_version"] = managed_prompt.version
    trace["prompt_source"] = managed_prompt.source

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
        client = OpenAI(api_key=key)
        resp = client.chat.completions.create(
            model=model_name,
            messages=messages,
            response_format={"type": "json_object"},
            temperature=0,
            max_tokens=400,
        )
        elapsed_s = time.perf_counter() - started
        content = resp.choices[0].message.content or "{}"
        raw = json.loads(content)
        result = _coerce(raw, expected_type)

        OCR_CLASSIFIER_CALLS.labels(
            document_type=expected_type, model=model_name, outcome="success",
        ).inc()
        OCR_CLASSIFIER_DURATION.labels(
            document_type=expected_type, model=model_name,
        ).observe(elapsed_s)
        if not result.matches_expected_type:
            OCR_CLASSIFIER_REJECTED.labels(
                expected_type=expected_type, reason="type_mismatch",
            ).inc()
        elif not result.looks_authentic:
            OCR_CLASSIFIER_REJECTED.labels(
                expected_type=expected_type, reason="not_authentic",
            ).inc()

        prompt_tokens = 0
        completion_tokens = 0
        usage = getattr(resp, "usage", None)
        if usage is not None:
            prompt_tokens = getattr(usage, "prompt_tokens", None) or 0
            completion_tokens = getattr(usage, "completion_tokens", None) or 0

        trace.update({
            "outcome": "success",
            "raw_response": content,
            "result": result.to_dict(),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "elapsed_ms": int(elapsed_s * 1000),
        })
        logger.info(
            "doc_classifier: expected=%s detected=%s matches=%s authentic=%s confidence=%.2f",
            expected_type, result.detected_type, result.matches_expected_type,
            result.looks_authentic, result.confidence,
        )
        langfuse_client.log_generation(
            langfuse_trace,
            name=f"doc-classifier.{expected_type}",
            model=model_name,
            messages=messages,
            response_text=content,
            parsed_output=result.to_dict(),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            elapsed_ms=int(elapsed_s * 1000),
            outcome="success",
            prompt_obj=managed_prompt.langfuse_obj,
            metadata={
                "expected_type": expected_type,
                "detected_type": result.detected_type,
                "matches_expected_type": result.matches_expected_type,
                "looks_authentic": result.looks_authentic,
                "confidence": result.confidence,
                "prompt_source": managed_prompt.source,
            },
        )
        return result, trace
    except Exception as exc:  # noqa: BLE001
        OCR_CLASSIFIER_CALLS.labels(
            document_type=expected_type, model=model_name, outcome="error",
        ).inc()
        OCR_CLASSIFIER_DURATION.labels(
            document_type=expected_type, model=model_name,
        ).observe(time.perf_counter() - started)
        logger.warning("doc_classifier: %s failed: %s", expected_type, exc)
        # Fail-open on transient errors — see comment on skipped_no_key.
        trace.update({
            "outcome": "error",
            "error": str(exc),
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        })
        langfuse_client.log_generation(
            langfuse_trace,
            name=f"doc-classifier.{expected_type}",
            model=model_name,
            messages=messages,
            response_text=None,
            parsed_output=None,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            outcome="error",
            error=str(exc),
            prompt_obj=managed_prompt.langfuse_obj,
            metadata={"expected_type": expected_type, "prompt_source": managed_prompt.source},
        )
        return ClassificationResult(
            matches_expected_type=True,
            detected_type=None,
            confidence=0.0,
            looks_authentic=True,
            outcome="error",
            reasons=[f"classifier error: {exc}"[:120]],
        ), trace
