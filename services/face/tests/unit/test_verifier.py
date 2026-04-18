"""Unit tests for the face verifier decision engine.

All boto3 / Rekognition / liveness calls are mocked — these tests exercise
the decision logic (thresholds, validation, downgrades) in isolation.
"""

import pytest

from app.services import verifier


# ── Helpers ──────────────────────────────────────────────────────────────

def _face(
    confidence=99.0,
    brightness=80.0,
    sharpness=80.0,
    eyes_open=True,
    sunglasses=False,
):
    return {
        "confidence": confidence,
        "quality": {"brightness": brightness, "sharpness": sharpness},
        "eyes_open": eyes_open,
        "sunglasses": sunglasses,
    }


def _detect_single_face(**face_attrs):
    return {"face_count": 1, "faces": [_face(**face_attrs)]}


def _detect_no_face():
    return {"face_count": 0, "faces": []}


def _detect_multiple_faces(count=2):
    return {"face_count": count, "faces": [_face() for _ in range(count)]}


def _liveness(score=0.95, reasons=None):
    return {
        "liveness_score": score,
        "checks": {},
        "reasons": reasons or [],
    }


def _comparison(similarity=95.0):
    return {
        "similarity_score": similarity,
        "face_detected_selfie": True,
        "face_detected_reference": True,
        "processing_time_ms": 10,
    }


@pytest.fixture
def mock_rekognition(monkeypatch):
    """Default mocks: one good face everywhere, high liveness, high similarity."""
    calls = {"detect_calls": 0}

    def _detect_faces(path):
        calls["detect_calls"] += 1
        return _detect_single_face()

    monkeypatch.setattr(verifier, "detect_faces", _detect_faces)
    monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness())
    monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison())
    return calls


# ── verify() — happy path ─────────────────────────────────────────────────

class TestVerifyHappyPath:
    def test_clean_inputs_pass(self, mock_rekognition):
        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "pass"
        assert result["similarity_score"] == 95.0
        assert result["liveness_passed"] is True
        assert result["reasons"] == []

    def test_result_has_expected_shape(self, mock_rekognition):
        result = verifier.verify("selfie.jpg", "reference.jpg")
        expected_keys = {
            "similarity_score", "liveness_score", "liveness_passed",
            "face_quality", "decision", "reasons", "processing_time_ms",
        }
        assert set(result.keys()) == expected_keys


# ── verify() — hard failures (no face) ────────────────────────────────────

class TestVerifyNoFace:
    def test_no_face_in_selfie_fails_immediately(self, monkeypatch):
        monkeypatch.setattr(verifier, "detect_faces", lambda p: _detect_no_face())
        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "fail"
        assert result["similarity_score"] == 0.0
        assert result["liveness_score"] == 0.0
        assert any("No face detected" in r for r in result["reasons"])

    def test_no_face_in_reference_fails(self, monkeypatch):
        """Good selfie, no face in reference document."""
        call_count = {"n": 0}

        def _detect(path):
            call_count["n"] += 1
            # First call is selfie (good), second is reference (no face)
            if call_count["n"] == 1:
                return _detect_single_face()
            return _detect_no_face()

        monkeypatch.setattr(verifier, "detect_faces", _detect)
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness())
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison())

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "fail"
        assert any("No face detected in reference" in r for r in result["reasons"])


# ── verify() — similarity decision ────────────────────────────────────────

class TestVerifySimilarityThresholds:
    def test_similarity_below_review_threshold_fails(self, monkeypatch):
        monkeypatch.setattr(verifier, "detect_faces", lambda p: _detect_single_face())
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.95))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(50.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "fail"
        assert any("similarity too low" in r.lower() for r in result["reasons"])

    def test_similarity_in_review_range_is_manual_review(self, monkeypatch):
        """70 <= similarity < 90 → manual_review."""
        monkeypatch.setattr(verifier, "detect_faces", lambda p: _detect_single_face())
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.95))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(75.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "manual_review"
        assert any("borderline" in r.lower() for r in result["reasons"])

    def test_similarity_at_pass_threshold(self, monkeypatch):
        """similarity exactly 90 with passing liveness → pass."""
        monkeypatch.setattr(verifier, "detect_faces", lambda p: _detect_single_face())
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.95))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(90.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "pass"


# ── verify() — liveness decision ──────────────────────────────────────────

class TestVerifyLivenessThresholds:
    def test_liveness_below_review_fails(self, monkeypatch):
        """liveness < 0.5 → fail."""
        monkeypatch.setattr(verifier, "detect_faces", lambda p: _detect_single_face())
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.3))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(95.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "fail"
        assert result["liveness_passed"] is False

    def test_liveness_borderline_is_manual_review(self, monkeypatch):
        """0.5 <= liveness < 0.85 → manual_review."""
        monkeypatch.setattr(verifier, "detect_faces", lambda p: _detect_single_face())
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.7))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(95.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "manual_review"
        assert result["liveness_passed"] is False
        assert any("borderline" in r.lower() for r in result["reasons"])

    def test_liveness_at_pass_threshold(self, monkeypatch):
        """liveness exactly 0.85 → passes."""
        monkeypatch.setattr(verifier, "detect_faces", lambda p: _detect_single_face())
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.85))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(95.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "pass"
        assert result["liveness_passed"] is True


# ── verify() — soft validation issues downgrade pass → manual_review ──────

class TestVerifySoftDowngrade:
    @pytest.mark.parametrize("issue,face_override,reason_fragment", [
        ("sunglasses", {"sunglasses": True}, "sunglasses"),
        ("eyes_closed", {"eyes_open": False}, "eyes appear closed"),
        ("low_brightness", {"brightness": 5.0}, "too dark"),
        ("low_sharpness", {"sharpness": 5.0}, "too blurry"),
    ])
    def test_soft_issue_downgrades_pass_to_manual_review(
        self, monkeypatch, issue, face_override, reason_fragment
    ):
        """Good similarity + good liveness, but selfie has a soft validation issue
        (sunglasses/closed eyes/dim/blurry) → decision drops from pass to
        manual_review."""
        call_count = {"n": 0}

        def _detect(path):
            call_count["n"] += 1
            # First call (selfie) has the issue; second (reference) is clean
            if call_count["n"] == 1:
                return _detect_single_face(**face_override)
            return _detect_single_face()

        monkeypatch.setattr(verifier, "detect_faces", _detect)
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.95))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(95.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "manual_review"
        assert any(reason_fragment.lower() in r.lower() for r in result["reasons"])

    def test_multiple_faces_in_selfie_downgrades(self, monkeypatch):
        call_count = {"n": 0}

        def _detect(path):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return _detect_multiple_faces(3)
            return _detect_single_face()

        monkeypatch.setattr(verifier, "detect_faces", _detect)
        monkeypatch.setattr(verifier, "assess_liveness", lambda p: _liveness(0.95))
        monkeypatch.setattr(verifier, "compare_faces", lambda s, r: _comparison(95.0))

        result = verifier.verify("selfie.jpg", "reference.jpg")
        assert result["decision"] == "manual_review"
        assert any("multiple faces" in r.lower() for r in result["reasons"])


# ── verify_with_liveness_session() ────────────────────────────────────────

class TestVerifyWithLivenessSession:
    def test_passed_liveness_high_similarity_is_pass(self, monkeypatch, tmp_path):
        """Rekognition Liveness succeeded + similarity 95 → pass."""
        doc = tmp_path / "ref_doc.jpg"
        doc.write_bytes(b"fake image data")

        monkeypatch.setattr(
            verifier, "compare_faces_bytes",
            lambda src, tgt: _comparison(95.0),
        )

        result = verifier.verify_with_liveness_session(
            liveness_confidence=95.0,
            liveness_passed=True,
            liveness_reference_image=b"captured_face_bytes",
            reference_doc_path=str(doc),
        )
        assert result["decision"] == "pass"
        assert result["similarity_score"] == 95.0
        assert result["liveness_score"] == 0.95

    def test_failed_liveness_is_fail(self, monkeypatch, tmp_path):
        doc = tmp_path / "ref_doc.jpg"
        doc.write_bytes(b"fake image data")

        result = verifier.verify_with_liveness_session(
            liveness_confidence=45.0,
            liveness_passed=False,
            liveness_reference_image=b"captured_face_bytes",
            reference_doc_path=str(doc),
        )
        assert result["decision"] == "fail"
        assert result["liveness_passed"] is False

    def test_missing_reference_image_records_reason(self):
        result = verifier.verify_with_liveness_session(
            liveness_confidence=95.0,
            liveness_passed=True,
            liveness_reference_image=None,
            reference_doc_path="/any/path.jpg",
        )
        assert result["similarity_score"] == 0.0
        assert any("reference image" in r.lower() for r in result["reasons"])

    def test_similarity_borderline_is_manual_review(self, monkeypatch, tmp_path):
        doc = tmp_path / "ref_doc.jpg"
        doc.write_bytes(b"fake image data")

        monkeypatch.setattr(
            verifier, "compare_faces_bytes",
            lambda src, tgt: _comparison(80.0),  # in review range
        )

        result = verifier.verify_with_liveness_session(
            liveness_confidence=95.0,
            liveness_passed=True,
            liveness_reference_image=b"captured_face_bytes",
            reference_doc_path=str(doc),
        )
        assert result["decision"] == "manual_review"

    def test_similarity_below_review_is_fail(self, monkeypatch, tmp_path):
        doc = tmp_path / "ref_doc.jpg"
        doc.write_bytes(b"fake image data")

        monkeypatch.setattr(
            verifier, "compare_faces_bytes",
            lambda src, tgt: _comparison(50.0),
        )

        result = verifier.verify_with_liveness_session(
            liveness_confidence=95.0,
            liveness_passed=True,
            liveness_reference_image=b"captured_face_bytes",
            reference_doc_path=str(doc),
        )
        assert result["decision"] == "fail"
