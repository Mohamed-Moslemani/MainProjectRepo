"""Crop the principal face out of a document image.

Lebanese IDs and passports carry the holder's photo in a small region
of an otherwise cluttered page (Arabic calligraphy, stamps, watermarks,
sometimes a ghost portrait). Sending the full document to Rekognition
CompareFaces means Rekognition makes its own internal "which face is
the real one?" call; on cluttered scans it occasionally locks onto a
secondary region (signature, stamp face-like artefact) and returns a
similarity score that doesn't reflect the principal photo.

This module makes that decision explicit and auditable:
1. Run DetectFaces on the document.
2. Pick the largest detected face (by bounding-box area).
3. Crop with ~15% padding so eyebrows / chin clear the box.
4. Return JPEG bytes + metadata (bbox, confidence, source hash, count).

The cropped bytes are then passed to compare_faces_bytes alongside
the liveness selfie. The metadata is persisted by the caller so an
auditor can replay the exact crop a similarity score was scored on.

Failure modes:
- No face: return None and let the caller surface the existing
  "no face on reference" path.
- Multiple faces: pick the largest; surface the count so the caller
  can downgrade `pass` → `manual_review` (a passport-sized photo
  shouldn't have neighbours).
- PIL failure: fall back to the raw bytes so we never block on a
  crop bug — comparison still runs, just without the cleanup.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

from ..config import get_settings
from .rekognition import detect_faces

logger = logging.getLogger(__name__)


# Padding around the detected face bbox, as a fraction of the bbox
# width/height. 15% empirically clears eyebrows + chin on a passport
# photo without pulling in too much of the surrounding card.
_PADDING = 0.15


@dataclass
class FaceCrop:
    """Result of crop_principal_face — bytes plus enough metadata to
    reproduce + audit the decision later."""

    bytes: bytes
    bbox: dict      # {"left", "top", "width", "height"} — fractions of source
    confidence: float
    face_count: int
    width: int
    height: int
    used_fallback: bool  # True when the crop pipeline failed and we returned raw bytes

    def to_audit_dict(self) -> dict:
        return {
            "bbox":          self.bbox,
            "confidence":    self.confidence,
            "face_count":    self.face_count,
            "width":         self.width,
            "height":        self.height,
            "used_fallback": self.used_fallback,
        }


def crop_principal_face(image_path: str) -> FaceCrop | None:
    """Detect, pick, and crop the principal face on a document page.

    Returns None when no face was detected — the caller is expected
    to surface that as the "no face on reference" path (existing
    behaviour) so the citizen sees a clear retake reason.
    """
    # In mock mode the image_path is typically a fake fixture path;
    # we never actually decode it. Return a deterministic stub so
    # E2E tests have something to pass into compare_faces_bytes.
    if get_settings().mock_mode:
        return FaceCrop(
            bytes=b"MOCK_CROPPED_FACE_BYTES",
            bbox={"left": 0.05, "top": 0.10, "width": 0.30, "height": 0.40},
            confidence=99.5, face_count=1, width=0, height=0,
            used_fallback=False,
        )

    detection = detect_faces(image_path)
    face_count = detection.get("face_count", 0)
    if face_count == 0:
        return None

    # Largest face wins. Passport pages occasionally carry a
    # ghost / hologram photo that's a fraction of the principal's
    # size; comparing against the ghost would produce a misleading
    # similarity. Pick by bbox area.
    faces = detection.get("faces") or []
    principal = max(
        faces,
        key=lambda f: (
            (f.get("bounding_box", {}).get("width") or 0.0)
            * (f.get("bounding_box", {}).get("height") or 0.0)
        ),
    )
    bbox = principal.get("bounding_box") or {}
    confidence = float(principal.get("confidence") or 0.0)

    try:
        from PIL import Image
    except ImportError:
        logger.warning(
            "Pillow not installed — cannot crop face, falling back to raw bytes",
        )
        with open(image_path, "rb") as fh:
            raw = fh.read()
        return FaceCrop(
            bytes=raw, bbox=bbox, confidence=confidence,
            face_count=face_count, width=0, height=0, used_fallback=True,
        )

    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            W, H = img.size
            l = max(0.0, bbox.get("left",   0.0) - _PADDING * bbox.get("width",  0.0))
            t = max(0.0, bbox.get("top",    0.0) - _PADDING * bbox.get("height", 0.0))
            r = min(1.0, bbox.get("left",   0.0) + (1 + _PADDING) * bbox.get("width",  0.0))
            b = min(1.0, bbox.get("top",    0.0) + (1 + _PADDING) * bbox.get("height", 0.0))
            crop = img.crop((int(l * W), int(t * H), int(r * W), int(b * H)))

            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=92)
            buf.seek(0)
            cropped_bytes = buf.read()
            cw, ch = crop.size

        return FaceCrop(
            bytes=cropped_bytes,
            bbox=bbox,
            confidence=confidence,
            face_count=face_count,
            width=cw, height=ch,
            used_fallback=False,
        )
    except Exception as exc:  # noqa: BLE001 — crop must never block the pipeline
        logger.warning("Face crop failed for %s: %s — falling back to raw bytes", image_path, exc)
        with open(image_path, "rb") as fh:
            raw = fh.read()
        return FaceCrop(
            bytes=raw, bbox=bbox, confidence=confidence,
            face_count=face_count, width=0, height=0, used_fallback=True,
        )
