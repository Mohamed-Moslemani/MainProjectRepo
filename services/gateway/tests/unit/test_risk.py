"""Unit tests for the risk scoring service."""

import pytest

from app.services.risk import (
    compute_risk_score,
    AUTO_APPROVE_THRESHOLD,
    MANUAL_REVIEW_THRESHOLD,
    SERVICE_SEVERITY,
    WEIGHTS,
)


def _perfect(service_type="id_renewal", **overrides):
    """Build kwargs for a perfectly clean submission (no risk signals)."""
    base = dict(
        ocr_avg_confidence=1.0,
        face_similarity=100.0,
        liveness_score=1.0,
        reconciliation_integrity=1.0,
        document_quality_avg=1.0,
        service_type=service_type,
        mismatch_count=0,
        duplicate_detected=False,
    )
    base.update(overrides)
    return base


class TestWeightsAndConfig:
    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_service_severity_strictness_order(self):
        """Passport stricter than ID; new stricter than renewal."""
        assert SERVICE_SEVERITY["id_renewal"] < SERVICE_SEVERITY["id_new"]
        assert SERVICE_SEVERITY["id_new"] < SERVICE_SEVERITY["passport_renewal"]
        assert SERVICE_SEVERITY["passport_renewal"] < SERVICE_SEVERITY["passport_new"]

    def test_threshold_ordering(self):
        assert AUTO_APPROVE_THRESHOLD < MANUAL_REVIEW_THRESHOLD


class TestHappyPath:
    def test_perfect_id_renewal_auto_approves(self):
        result = compute_risk_score(**_perfect())
        # severity 20 * 0.1 = 2, everything else 0
        assert result["risk_score"] == 2.0
        assert result["routing"] == "auto_approve"

    def test_perfect_passport_new_still_auto_approves(self):
        """Even strictest service auto-approves when everything is clean."""
        result = compute_risk_score(**_perfect(service_type="passport_new"))
        # severity 80 * 0.1 = 8
        assert result["risk_score"] == 8.0
        assert result["routing"] == "auto_approve"


class TestBadPath:
    def test_all_signals_bad_rejects_id_renewal(self):
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=0.0,
            liveness_score=0.0,
            reconciliation_integrity=0.0,
            document_quality_avg=0.0,
            service_type="id_renewal",
        )
        # 0.15*100 + 0.2*100 + 0.2*100 + 0.25*100 + 0.1*100 + 0.1*20 = 92
        assert result["risk_score"] == 92.0
        assert result["routing"] == "reject"

    def test_all_signals_bad_rejects_passport_new(self):
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=0.0,
            liveness_score=0.0,
            reconciliation_integrity=0.0,
            document_quality_avg=0.0,
            service_type="passport_new",
        )
        # + severity 80*0.1 = 8 → 98
        assert result["risk_score"] == 98.0
        assert result["routing"] == "reject"


class TestRoutingBoundaries:
    def test_at_auto_approve_threshold(self):
        """Exactly 25 should still auto_approve (the check is `<=`)."""
        # id_renewal severity=2; need reconciliation to contribute 23.
        # 0.25 * R = 23 → R = 92 → integrity = 0.08
        result = compute_risk_score(
            ocr_avg_confidence=1.0,
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=0.08,
            document_quality_avg=1.0,
            service_type="id_renewal",
        )
        assert result["risk_score"] == pytest.approx(25.0, abs=0.02)
        assert result["routing"] == "auto_approve"

    def test_just_over_auto_approve_is_manual_review(self):
        """Score 25.01 should route to manual_review."""
        result = compute_risk_score(
            ocr_avg_confidence=0.999,  # tiny OCR risk pushes us over
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=0.08,
            document_quality_avg=1.0,
            service_type="id_renewal",
        )
        assert result["risk_score"] > AUTO_APPROVE_THRESHOLD
        assert result["routing"] == "manual_review"

    def test_at_manual_review_threshold(self):
        """Exactly 60 should still manual_review (the check is `<=`).

        Lever: all 5 non-severity signals at 0.5 + severity passport_new (8):
        0.15*50 + 0.2*50 + 0.2*50 + 0.25*50 + 0.1*50 + 8 = 7.5+10+10+12.5+5+8 = 53.
        Add one mismatch (+8) = 61 → over.
        Better: use half-risk signals + tuned reconciliation.
        Simplest: pick inputs that compute exactly to 60.
        0.25 * R + 8 = 60 (passport_new severity 8) → R = 208 — too high.
        Mix: full recon mismatch (25) + quality_risk 90 (9) + severity 8 + ocr_risk 80 (12) + face 90 (22.5) = too high.
        Use parametric: all risks at 0.52 (uniform) in passport_new:
        total = (0.15+0.2+0.2+0.25+0.1) * 52 + 8 = 0.9*52 + 8 = 46.8 + 8 = 54.8
        We'll use mismatch penalty to dial precisely.
        """
        # All-perfect passport_new + 6 mismatches + reconciliation penalty
        # severity 8 + 6*8 mismatches = 56. Need reconciliation_risk = 16 → integrity 0.84
        result = compute_risk_score(
            ocr_avg_confidence=1.0,
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=0.84,
            document_quality_avg=1.0,
            service_type="passport_new",
            mismatch_count=6,
        )
        assert result["risk_score"] == pytest.approx(60.0, abs=0.5)
        assert result["routing"] == "manual_review"

    def test_just_over_manual_review_is_reject(self):
        """Score > 60 should route to reject.

        All-bad id_renewal scores 92 → reject. All-bad passport_new scores 98 → reject.
        A simpler case: half-bad signals + a duplicate.
        """
        result = compute_risk_score(
            ocr_avg_confidence=0.5,
            face_similarity=50.0,
            liveness_score=0.5,
            reconciliation_integrity=0.5,
            document_quality_avg=0.5,
            service_type="passport_new",
            duplicate_detected=True,  # +30
        )
        assert result["risk_score"] > MANUAL_REVIEW_THRESHOLD
        assert result["routing"] == "reject"


class TestMismatchPenalty:
    def test_one_mismatch_adds_eight(self):
        clean = compute_risk_score(**_perfect())
        with_mismatch = compute_risk_score(**_perfect(mismatch_count=1))
        assert with_mismatch["risk_score"] - clean["risk_score"] == pytest.approx(8.0)

    def test_three_mismatches_adds_twenty_four(self):
        clean = compute_risk_score(**_perfect())
        with_mismatches = compute_risk_score(**_perfect(mismatch_count=3))
        assert with_mismatches["risk_score"] - clean["risk_score"] == pytest.approx(24.0)

    def test_mismatch_can_push_auto_approve_to_manual_review(self):
        """Clean id_renewal scores 2; 3 mismatches bump it to 26 → manual_review."""
        result = compute_risk_score(**_perfect(mismatch_count=3))
        assert result["risk_score"] == 26.0
        assert result["routing"] == "manual_review"

    def test_mismatch_penalty_appears_in_breakdown(self):
        result = compute_risk_score(**_perfect(mismatch_count=2))
        assert result["breakdown"]["mismatch_penalty"] == 16


class TestDuplicatePenalty:
    def test_duplicate_adds_thirty(self):
        clean = compute_risk_score(**_perfect())
        dup = compute_risk_score(**_perfect(duplicate_detected=True))
        assert dup["risk_score"] - clean["risk_score"] == pytest.approx(30.0)

    def test_duplicate_penalty_appears_in_breakdown(self):
        result = compute_risk_score(**_perfect(duplicate_detected=True))
        assert result["breakdown"]["duplicate_penalty"] == 30

    def test_no_duplicate_has_zero_penalty(self):
        result = compute_risk_score(**_perfect())
        assert result["breakdown"]["duplicate_penalty"] == 0


class TestClamping:
    def test_score_capped_at_100(self):
        """Extreme bad inputs + many mismatches + duplicate must not exceed 100."""
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=0.0,
            liveness_score=0.0,
            reconciliation_integrity=0.0,
            document_quality_avg=0.0,
            service_type="passport_new",
            mismatch_count=20,
            duplicate_detected=True,
        )
        assert result["risk_score"] == 100.0
        assert result["routing"] == "reject"

    def test_score_floor_at_zero(self):
        """compute_risk_score should never return negative, even if inputs
        are slightly out of [0,1] due to upstream rounding."""
        result = compute_risk_score(
            ocr_avg_confidence=1.1,
            face_similarity=100.0,
            liveness_score=1.05,
            reconciliation_integrity=1.0,
            document_quality_avg=1.0,
            service_type="id_renewal",
            mismatch_count=0,
        )
        assert result["risk_score"] >= 0


class TestUnknownServiceType:
    def test_unknown_service_falls_back_to_default_severity(self):
        result = compute_risk_score(**_perfect(service_type="bogus_service"))
        # default severity 0.5 → severity_risk 50 → 50 * 0.1 = 5
        assert result["risk_score"] == 5.0
        assert result["routing"] == "auto_approve"


class TestBreakdownStructure:
    def test_breakdown_has_all_expected_keys(self):
        result = compute_risk_score(**_perfect(mismatch_count=2, duplicate_detected=True))
        expected_keys = {
            "ocr_risk", "face_risk", "liveness_risk",
            "reconciliation_risk", "quality_risk", "severity",
            "mismatch_penalty", "duplicate_penalty",
        }
        assert set(result["breakdown"].keys()) == expected_keys

    def test_result_has_score_routing_breakdown(self):
        result = compute_risk_score(**_perfect())
        assert set(result.keys()) == {"risk_score", "routing", "breakdown"}


class TestComponentContributions:
    """Each component should contribute exactly its weighted share."""

    def test_only_ocr_risk(self):
        """ocr=0 → ocr_risk=100 → contributes 15. Plus id_renewal severity 2 → 17."""
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=1.0,
            document_quality_avg=1.0,
            service_type="id_renewal",
        )
        assert result["risk_score"] == 17.0
        assert result["breakdown"]["ocr_risk"] == 100.0

    def test_only_face_risk(self):
        """face_similarity=50 → face_risk=50 → contributes 10. + severity 2 → 12."""
        result = compute_risk_score(
            ocr_avg_confidence=1.0,
            face_similarity=50.0,
            liveness_score=1.0,
            reconciliation_integrity=1.0,
            document_quality_avg=1.0,
            service_type="id_renewal",
        )
        assert result["risk_score"] == 12.0
        assert result["breakdown"]["face_risk"] == 50.0

    def test_only_reconciliation_risk(self):
        """reconciliation=0.5 → risk 50 → contributes 12.5. + severity 2 → 14.5."""
        result = compute_risk_score(
            ocr_avg_confidence=1.0,
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=0.5,
            document_quality_avg=1.0,
            service_type="id_renewal",
        )
        assert result["risk_score"] == 14.5
