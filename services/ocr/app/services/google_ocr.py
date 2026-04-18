"""Google Cloud Vision OCR integration."""

import time
import logging

from ..config import get_settings
from .mocks import mock_extract_text

logger = logging.getLogger(__name__)


def extract_text(image_path: str, document_type: str | None = None) -> dict:
    """Run Google Cloud Vision OCR on an image and return raw text + annotations.

    If OCR_MOCK_MODE is set, returns a deterministic fixture instead of
    calling Google Vision. The document_type is forwarded to the mock so
    fixtures can match the expected layout (national_id, passport, etc.);
    it is unused in live mode.
    """
    if get_settings().mock_mode:
        logger.info("OCR mock mode active — returning fixture for %s", document_type)
        return mock_extract_text(image_path, document_type)

    # Lazy import so mock mode doesn't require google-cloud-vision at all.
    from google.cloud import vision
    from ..clients import get_vision_client

    client = get_vision_client()

    with open(image_path, "rb") as f:
        content = f.read()

    image = vision.Image(content=content)

    start = time.time()
    response = client.document_text_detection(image=image)
    elapsed_ms = int((time.time() - start) * 1000)

    if response.error.message:
        raise RuntimeError(f"Google Vision API error: {response.error.message}")

    full_text = response.full_text_annotation.text if response.full_text_annotation else ""

    words = []
    if response.full_text_annotation:
        for page in response.full_text_annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        word_text = "".join(s.text for s in word.symbols)
                        words.append({
                            "text": word_text,
                            "confidence": word.confidence,
                        })

    return {
        "full_text": full_text,
        "words": words,
        "processing_time_ms": elapsed_ms,
    }
