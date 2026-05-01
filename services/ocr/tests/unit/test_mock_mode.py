"""Tests for OCR_MOCK_MODE=1 short-circuit behaviour."""

import pytest

from app import config as config_module
from app.services.google_ocr import extract_text
from app.services.quality import assess_quality
from app.services.mocks import mock_extract_text, mock_assess_quality


@pytest.fixture
def mock_mode(monkeypatch):
    """Enable OCR_MOCK_MODE for the duration of a test."""
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("OCR_MOCK_MODE", "true")
    yield
    config_module.get_settings.cache_clear()


class TestExtractTextMockMode:
    def test_returns_fixture_when_mock_mode_on(self, mock_mode):
        """With mock mode on, extract_text should not touch Google Vision
        and should return the national_id fixture text."""
        result = extract_text("/nonexistent/path.jpg", "national_id")
        assert "Mohamed Saad" in result["full_text"]
        assert len(result["words"]) > 0
        assert all(w["confidence"] == 0.95 for w in result["words"])

    def test_passport_fixture_includes_mrz(self, mock_mode):
        result = extract_text("/nonexistent.jpg", "old_passport_data_page")
        assert "P<LBN" in result["full_text"]
        assert "LR12345676" in result["full_text"]

    def test_birth_certificate_fixture(self, mock_mode):
        result = extract_text("/nonexistent.jpg", "birth_certificate")
        assert "Birth Certificate" in result["full_text"]
        assert "Register No: 98765" in result["full_text"]

    def test_unknown_document_type_falls_back_to_national_id(self, mock_mode):
        result = extract_text("/nonexistent.jpg", "bogus_doc_type")
        assert "Mohamed Saad" in result["full_text"]


class TestAssessQualityMockMode:
    def test_returns_clean_fixture_when_mock_mode_on(self, mock_mode):
        """assess_quality should skip cv2 and return a clean-readable fixture."""
        result = assess_quality("/does/not/exist.jpg")
        assert result["is_readable"] is True
        assert result["is_blurry"] is False
        assert result["glare_detected"] is False
        assert result["resolution_ok"] is True
        assert result["angle_ok"] is True
        assert result["issues"] == []


class TestMockFixtureShapes:
    """Mocks should produce the exact same shape as the real functions."""

    def test_mock_extract_text_shape(self):
        result = mock_extract_text("/x.jpg", "national_id")
        assert set(result.keys()) == {"full_text", "words", "processing_time_ms"}
        assert isinstance(result["words"], list)
        for w in result["words"]:
            assert "text" in w
            assert "confidence" in w

    def test_mock_assess_quality_shape(self):
        result = mock_assess_quality("/x.jpg")
        expected = {
            "is_readable", "is_blurry", "blur_score",
            "glare_detected", "angle_ok", "resolution_ok", "issues",
        }
        assert set(result.keys()) == expected


class TestMockModeDisabledByDefault:
    def test_settings_mock_mode_defaults_to_false(self, monkeypatch):
        """Without the env var, mock_mode is False."""
        config_module.get_settings.cache_clear()
        monkeypatch.delenv("OCR_MOCK_MODE", raising=False)
        s = config_module.get_settings()
        assert s.mock_mode is False
        config_module.get_settings.cache_clear()
