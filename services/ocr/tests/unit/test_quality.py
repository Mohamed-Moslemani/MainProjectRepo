"""Unit tests for the OCR image quality assessment.

Uses synthetic images generated at test time (cv2 + numpy) — no real files
on disk to manage, and no cv2 mocking.
"""

import cv2
import numpy as np
import pytest

from app.services.quality import assess_quality


# ── Helpers ──────────────────────────────────────────────────────────────

def _write(tmp_path, name, img):
    p = tmp_path / name
    cv2.imwrite(str(p), img)
    return str(p)


def _noise_image(h=1000, w=1000):
    """High-entropy noise → high Laplacian variance → sharp."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, (h, w, 3), dtype=np.uint8)


def _document_image(h=1000, w=1000):
    """Noise image with a clean horizontal + vertical border so the
    Hough-transform skew check finds aligned edges. Mimics a scanned doc."""
    img = _noise_image(h, w)
    border = 20
    img[0:border, :] = 0           # top bar
    img[h - border:h, :] = 0       # bottom bar
    img[:, 0:border] = 0           # left bar
    img[:, w - border:w] = 0       # right bar
    return img


def _flat_image(h=1000, w=1000, value=128):
    """Uniform color → Laplacian variance ≈ 0 → detected as blurry."""
    return np.full((h, w, 3), value, dtype=np.uint8)


def _image_with_glare(h=1000, w=1000):
    """Noise image + large bright (overexposed) region."""
    img = _noise_image(h, w)
    # Paint a white block covering ~10% of the image
    side = int(h * 0.32)  # ~10% of area
    img[0:side, 0:side] = 255
    return img


# ── Output shape ─────────────────────────────────────────────────────────

class TestOutputShape:
    def test_result_has_expected_keys(self, tmp_path):
        path = _write(tmp_path, "x.jpg", _document_image())
        result = assess_quality(path)
        expected = {
            "is_readable", "is_blurry", "blur_score",
            "glare_detected", "angle_ok", "resolution_ok", "issues",
        }
        assert set(result.keys()) == expected


# ── Invalid file ─────────────────────────────────────────────────────────

class TestInvalidFile:
    def test_missing_file_not_readable(self, tmp_path):
        result = assess_quality(str(tmp_path / "does_not_exist.jpg"))
        assert result["is_readable"] is False
        assert "Could not read image file" in result["issues"]

    def test_missing_file_does_not_raise(self, tmp_path):
        assess_quality(str(tmp_path / "missing.jpg"))  # should not crash


# ── Blur detection ───────────────────────────────────────────────────────

class TestBlur:
    def test_noise_image_not_blurry(self, tmp_path):
        """Random-pixel image has very high Laplacian variance."""
        path = _write(tmp_path, "sharp.jpg", _document_image())
        result = assess_quality(path)
        assert result["is_blurry"] is False
        assert result["blur_score"] > 100.0

    def test_flat_image_detected_as_blurry(self, tmp_path):
        """Uniform-color image has near-zero Laplacian variance."""
        path = _write(tmp_path, "flat.jpg", _flat_image())
        result = assess_quality(path)
        assert result["is_blurry"] is True
        assert result["blur_score"] < 100.0
        assert any("blurry" in s.lower() for s in result["issues"])

    def test_blur_score_is_a_number(self, tmp_path):
        path = _write(tmp_path, "x.jpg", _document_image())
        result = assess_quality(path)
        assert isinstance(result["blur_score"], float)
        assert result["blur_score"] >= 0


# ── Glare detection ──────────────────────────────────────────────────────

class TestGlare:
    def test_noise_image_no_glare(self, tmp_path):
        path = _write(tmp_path, "clean.jpg", _document_image())
        result = assess_quality(path)
        assert result["glare_detected"] is False

    def test_overexposed_region_detected_as_glare(self, tmp_path):
        path = _write(tmp_path, "glary.jpg", _image_with_glare())
        result = assess_quality(path)
        assert result["glare_detected"] is True
        assert any("glare" in s.lower() for s in result["issues"])


# ── Resolution check ─────────────────────────────────────────────────────

class TestResolution:
    def test_large_image_passes_resolution(self, tmp_path):
        path = _write(tmp_path, "big.jpg", _noise_image(h=1080, w=1920))
        result = assess_quality(path)
        assert result["resolution_ok"] is True

    def test_small_image_fails_resolution(self, tmp_path):
        """100x100 is below the 640x480 minimum."""
        path = _write(tmp_path, "tiny.jpg", _noise_image(h=100, w=100))
        result = assess_quality(path)
        assert result["resolution_ok"] is False
        assert any("resolution" in s.lower() for s in result["issues"])

    def test_just_below_minimum_fails(self, tmp_path):
        """639x479 is one pixel below min on each dim."""
        path = _write(tmp_path, "almost.jpg", _noise_image(h=479, w=639))
        result = assess_quality(path)
        assert result["resolution_ok"] is False


# ── Overall readability ──────────────────────────────────────────────────

class TestReadability:
    def test_clean_noise_image_is_readable(self, tmp_path):
        """is_readable = not blurry AND no glare AND resolution ok.
        (Skew is tracked separately in angle_ok; doesn't affect is_readable.)"""
        path = _write(tmp_path, "ok.jpg", _document_image())
        result = assess_quality(path)
        assert result["is_readable"] is True
        assert result["is_blurry"] is False
        assert result["glare_detected"] is False
        assert result["resolution_ok"] is True

    def test_flat_image_is_not_readable(self, tmp_path):
        """Flat image is detected as blurry → not readable."""
        path = _write(tmp_path, "flat.jpg", _flat_image())
        result = assess_quality(path)
        assert result["is_readable"] is False

    def test_small_image_is_not_readable(self, tmp_path):
        path = _write(tmp_path, "tiny.jpg", _noise_image(h=100, w=100))
        result = assess_quality(path)
        assert result["is_readable"] is False


# ── is_blurry flag is a proper bool ──────────────────────────────────────

class TestIsBlurryFlagType:
    def test_is_blurry_is_python_bool(self, tmp_path):
        """Regression: Day 1 metrics wiring relies on is_blurry being a
        regular bool, not numpy.bool_ (which serialises weirdly in JSON)."""
        path = _write(tmp_path, "flat.jpg", _flat_image())
        result = assess_quality(path)
        assert type(result["is_blurry"]) is bool
