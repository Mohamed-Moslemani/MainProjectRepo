"""Content-based file type detection.

The mime type a browser puts on `file.content_type` is whatever the
upload header says — trivially spoofable by anyone using curl. Real
defence is to look at the first few bytes of the file ("magic bytes")
and compare against known signatures for the formats we accept.

We accept JPEG, PNG, WEBP, and PDF. This module implements just
those four signatures rather than pulling in a full libmagic
dependency — the universe of "things that could legitimately be
uploaded as a Lebanese identity document" is small, and a tight
allowlist beats a fuzzy detector for security.
"""

from __future__ import annotations


# Each entry is a list of (offset, prefix) pairs that must all match.
# Multiple alternatives per format are stacked as nested lists.
_SIGNATURES: dict[str, list[list[tuple[int, bytes]]]] = {
    "image/jpeg": [
        [(0, b"\xff\xd8\xff")],
    ],
    "image/png": [
        [(0, b"\x89PNG\r\n\x1a\n")],
    ],
    "image/webp": [
        # WEBP layout: "RIFF" + 4-byte size + "WEBP"
        [(0, b"RIFF"), (8, b"WEBP")],
    ],
    "application/pdf": [
        [(0, b"%PDF-")],
    ],
}


def detect_mime(blob: bytes) -> str | None:
    """Return the first matching mime type, or None if no signature
    matches. We only look at the first ~16 bytes of the file — that's
    enough for everything in our allowlist."""
    head = blob[:16]
    for mime, alternatives in _SIGNATURES.items():
        for sig in alternatives:
            if all(head[off:off + len(prefix)] == prefix for off, prefix in sig):
                return mime
    return None


def matches(blob: bytes, expected_mime: str) -> bool:
    """True if the bytes look like the expected mime type. Used to
    confirm the client-declared mime against the actual file."""
    detected = detect_mime(blob)
    if detected is None:
        return False
    return detected == expected_mime
