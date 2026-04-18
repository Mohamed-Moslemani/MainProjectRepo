"""Google Cloud Vision OCR integration."""

import time
import logging

from google.cloud import vision

from ..clients import get_vision_client

logger = logging.getLogger(__name__)


def extract_text(image_path: str) -> dict:
    """Run Google Cloud Vision OCR on an image and return raw text + annotations."""
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
