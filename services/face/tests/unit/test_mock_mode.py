"""Tests for FACE_MOCK_MODE=1 short-circuit behaviour."""

import pytest

from app import config as config_module
from app.services.rekognition import (
    create_liveness_session,
    get_liveness_session_results,
    compare_faces,
    detect_faces,
    compare_faces_bytes,
)
from app.services.liveness import assess_liveness
from app.services.mocks import (
    mock_detect_faces,
    mock_compare_faces,
    mock_compare_faces_bytes,
    mock_create_liveness_session,
    mock_get_liveness_session_results,
    mock_assess_liveness,
)


@pytest.fixture
def mock_mode(monkeypatch):
    """Enable FACE_MOCK_MODE for the duration of a test."""
    config_module.get_settings.cache_clear()
    monkeypatch.setenv("FACE_MOCK_MODE", "true")
    yield
    config_module.get_settings.cache_clear()


class TestRekognitionMockMode:
    def test_detect_faces_returns_fixture(self, mock_mode):
        result = detect_faces("/nonexistent.jpg")
        assert result["face_count"] == 1
        assert result["faces"][0]["eyes_open"] is True
        assert result["faces"][0]["sunglasses"] is False

    def test_compare_faces_returns_high_similarity(self, mock_mode):
        result = compare_faces("/a.jpg", "/b.jpg")
        assert result["similarity_score"] == 95.0
        assert result["face_detected_selfie"] is True

    def test_compare_faces_bytes_returns_high_similarity(self, mock_mode):
        result = compare_faces_bytes(b"selfie-bytes", b"doc-bytes")
        assert result["similarity_score"] == 95.0

    def test_create_liveness_session_returns_fake_id(self, mock_mode):
        result = create_liveness_session()
        assert result["session_id"].startswith("mock-")

    def test_get_liveness_session_results_returns_succeeded(self, mock_mode):
        result = get_liveness_session_results("anything")
        assert result["status"] == "SUCCEEDED"
        assert result["confidence"] == 95.0
        assert result["reference_image"] is not None


class TestLivenessMockMode:
    def test_assess_liveness_returns_fixture(self, mock_mode):
        result = assess_liveness("/nonexistent.jpg")
        assert result["liveness_score"] == 0.95
        assert result["reasons"] == []
        assert all(result["checks"].values())


class TestMockFixtureShapes:
    def test_mock_detect_faces_shape(self):
        r = mock_detect_faces("/x.jpg")
        assert "face_count" in r
        assert "faces" in r
        f = r["faces"][0]
        # bounding_box was added so face_extractor.crop_principal_face
        # has a deterministic bbox to crop against in mock mode.
        assert set(f.keys()) == {
            "confidence", "quality", "eyes_open", "sunglasses", "bounding_box",
        }
        bbox = f["bounding_box"]
        assert set(bbox.keys()) == {"left", "top", "width", "height"}
        assert all(0.0 <= bbox[k] <= 1.0 for k in bbox)

    def test_mock_compare_faces_shape(self):
        r = mock_compare_faces("/a.jpg", "/b.jpg")
        assert set(r.keys()) == {
            "similarity_score", "face_detected_selfie",
            "face_detected_reference", "processing_time_ms",
        }

    def test_mock_create_session_shape(self):
        r = mock_create_liveness_session()
        assert "session_id" in r

    def test_mock_liveness_results_shape(self):
        r = mock_get_liveness_session_results("sid")
        assert set(r.keys()) == {"session_id", "status", "confidence", "reference_image"}

    def test_mock_assess_liveness_shape(self):
        r = mock_assess_liveness("/x.jpg")
        assert set(r.keys()) == {"liveness_score", "checks", "reasons"}


class TestMockModeDisabledByDefault:
    def test_settings_mock_mode_defaults_to_false(self, monkeypatch):
        config_module.get_settings.cache_clear()
        monkeypatch.delenv("FACE_MOCK_MODE", raising=False)
        s = config_module.get_settings()
        assert s.mock_mode is False
        config_module.get_settings.cache_clear()
