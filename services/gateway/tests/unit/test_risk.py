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
        registry_match_score=1.0,
        registry_deceased=False,
    )
    base.update(overrides)
    return base


class TestWeightsAndConfig:
    def test_weights_sum_to_one(self):
        assert sum(WEIGHTS.values()) == pytest.approx(1.0)

    def test_registry_has_highest_weight(self):
        """Registry is the authoritative identity check — it must outweigh
        all other signals."""
        assert WEIGHTS["registry_match"] >= max(
            w for k, w in WEIGHTS.items() if k != "registry_match"
        )

    def test_service_severity_strictness_order(self):
        """Passport stricter than ID; new stricter than renewal."""
        assert SERVICE_SEVERITY["id_renewal"] < SERVICE_SEVERITY["id_new"]
        assert SERVICE_SEVERITY["id_new"] < SERVICE_SEVERITY["passport_renewal"]
        assert SERVICE_SEVERITY["passport_renewal"] < SERVICE_SEVERITY["passport_new"]

    def test_threshold_ordering(self):
        assert AUTO_APPROVE_THRESHOLD < MANUAL_REVIEW_THRESHOLD


class TestHappyPath:
    def test_perfect_id_renewal_auto_approves(self):
        """id_renewal severity 0.2 * 100 * 0.05 = 1.0 — everything else 0."""
        result = compute_risk_score(**_perfect())
        assert result["risk_score"] == pytest.approx(1.0)
        assert result["routing"] == "auto_approve"

    def test_perfect_passport_new_still_auto_approves(self):
        """Even strictest service auto-approves when everything is clean."""
        result = compute_risk_score(**_perfect(service_type="passport_new"))
        # severity 0.8 * 100 * 0.05 = 4.0
        assert result["risk_score"] == pytest.approx(4.0)
        assert result["routing"] == "auto_approve"


class TestBadPath:
    def test_all_signals_bad_rejects_id_renewal(self):
        """Everything including registry_match_score is zero."""
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=0.0,
            liveness_score=0.0,
            reconciliation_integrity=0.0,
            document_quality_avg=0.0,
            service_type="id_renewal",
            registry_match_score=0.0,
        )
        # weighted: 25+20+15+15+10+10 + severity(20*0.05)=1 = 96.0
        assert result["risk_score"] == pytest.approx(96.0)
        assert result["routing"] == "reject"

    def test_all_signals_bad_rejects_passport_new(self):
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=0.0,
            liveness_score=0.0,
            reconciliation_integrity=0.0,
            document_quality_avg=0.0,
            service_type="passport_new",
            registry_match_score=0.0,
        )
        # 95 + severity (80*0.05)=4 = 99.0
        assert result["risk_score"] == pytest.approx(99.0)
        assert result["routing"] == "reject"


class TestRegistryDeceasedOverride:
    def test_deceased_overrides_everything_else(self):
        """Even with all signals perfect, deceased → 100 / reject."""
        result = compute_risk_score(**_perfect(registry_deceased=True))
        assert result["risk_score"] == 100.0
        assert result["routing"] == "reject"
        assert result["breakdown"]["registry_deceased_override"] is True

    def test_deceased_flag_appears_in_breakdown(self):
        result = compute_risk_score(**_perfect())
        assert result["breakdown"]["registry_deceased_override"] is False


class TestRegistryMatchScore:
    def test_no_registry_match_adds_25_points(self):
        """registry_match_score=0 contributes 0.25 * 100 = 25 points."""
        clean = compute_risk_score(**_perfect())
        no_match = compute_risk_score(**_perfect(registry_match_score=0.0))
        assert no_match["risk_score"] - clean["risk_score"] == pytest.approx(25.0)

    def test_partial_registry_match_scales_linearly(self):
        """registry_match_score=0.5 → risk_contribution 0.25 * 50 = 12.5."""
        result = compute_risk_score(**_perfect(registry_match_score=0.5))
        # clean id_renewal is 1.0; plus 12.5 registry risk = 13.5
        assert result["risk_score"] == pytest.approx(13.5)

    def test_registry_risk_appears_in_breakdown(self):
        result = compute_risk_score(**_perfect(registry_match_score=0.5))
        assert result["breakdown"]["registry_risk"] == pytest.approx(50.0)


class TestRoutingBoundaries:
    def test_at_auto_approve_threshold(self):
        """Score exactly 25 → auto_approve. Use registry_match as the lever:
        registry_match_score=0 → 25 points; plus id_renewal severity 1 = 26.
        Pull it back to 25 with a slightly-better registry_match_score."""
        # Need 0.25*R + 1 = 25 → R = 96 → registry_match_score = 0.04
        result = compute_risk_score(**_perfect(registry_match_score=0.04))
        assert result["risk_score"] == pytest.approx(25.0, abs=0.02)
        assert result["routing"] == "auto_approve"

    def test_just_over_auto_approve_is_manual_review(self):
        """registry_match_score=0 → 25 registry + 1 severity = 26 → review."""
        result = compute_risk_score(**_perfect(registry_match_score=0.0))
        assert result["risk_score"] == pytest.approx(26.0)
        assert result["routing"] == "manual_review"

    def test_just_over_manual_review_is_reject(self):
        """Half-bad everything + deceased-false."""
        result = compute_risk_score(
            ocr_avg_confidence=0.5,
            face_similarity=50.0,
            liveness_score=0.5,
            reconciliation_integrity=0.5,
            document_quality_avg=0.5,
            service_type="passport_new",
            registry_match_score=0.5,
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
        """Clean id_renewal = 1; 4 mismatches = +32 → 33 → manual_review."""
        result = compute_risk_score(**_perfect(mismatch_count=4))
        assert result["risk_score"] == pytest.approx(33.0)
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
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=0.0,
            liveness_score=0.0,
            reconciliation_integrity=0.0,
            document_quality_avg=0.0,
            service_type="passport_new",
            mismatch_count=20,
            duplicate_detected=True,
            registry_match_score=0.0,
        )
        assert result["risk_score"] == 100.0
        assert result["routing"] == "reject"

    def test_score_floor_at_zero(self):
        result = compute_risk_score(
            ocr_avg_confidence=1.1,
            face_similarity=100.0,
            liveness_score=1.05,
            reconciliation_integrity=1.0,
            document_quality_avg=1.0,
            service_type="id_renewal",
            mismatch_count=0,
            registry_match_score=1.0,
        )
        assert result["risk_score"] >= 0


class TestUnknownServiceType:
    def test_unknown_service_falls_back_to_default_severity(self):
        """Default severity 0.5 * 100 = 50; contribution 0.05 * 50 = 2.5."""
        result = compute_risk_score(**_perfect(service_type="bogus_service"))
        assert result["risk_score"] == pytest.approx(2.5)
        assert result["routing"] == "auto_approve"


class TestBreakdownStructure:
    def test_breakdown_has_all_expected_keys(self):
        result = compute_risk_score(**_perfect(mismatch_count=2, duplicate_detected=True))
        expected_keys = {
            "registry_risk", "ocr_risk", "face_risk", "liveness_risk",
            "reconciliation_risk", "severity",
            "mismatch_penalty", "duplicate_penalty",
            "registry_deceased_override",
        }
        assert set(result["breakdown"].keys()) == expected_keys

    def test_result_has_score_routing_breakdown(self):
        result = compute_risk_score(**_perfect())
        assert set(result.keys()) == {"risk_score", "routing", "breakdown"}


class TestComponentContributions:
    """Each component should contribute exactly its weighted share."""

    def test_only_ocr_risk(self):
        """ocr=0 → ocr_risk=100 → contributes 15. + severity 1 → 16."""
        result = compute_risk_score(
            ocr_avg_confidence=0.0,
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=1.0,
            document_quality_avg=1.0,
            service_type="id_renewal",
            registry_match_score=1.0,
        )
        assert result["risk_score"] == pytest.approx(16.0)
        assert result["breakdown"]["ocr_risk"] == 100.0

    def test_only_face_risk(self):
        """face 50 → risk 50 → contributes 10. + severity 1 → 11."""
        result = compute_risk_score(
            ocr_avg_confidence=1.0,
            face_similarity=50.0,
            liveness_score=1.0,
            reconciliation_integrity=1.0,
            document_quality_avg=1.0,
            service_type="id_renewal",
            registry_match_score=1.0,
        )
        assert result["risk_score"] == pytest.approx(11.0)
        assert result["breakdown"]["face_risk"] == 50.0

    def test_only_reconciliation_risk(self):
        """recon 0.5 → risk 50 → contributes 10. + severity 1 → 11."""
        result = compute_risk_score(
            ocr_avg_confidence=1.0,
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=0.5,
            document_quality_avg=1.0,
            service_type="id_renewal",
            registry_match_score=1.0,
        )
        assert result["risk_score"] == pytest.approx(11.0)

    def test_only_registry_risk(self):
        """registry 0.0 → risk 100 → contributes 25. + severity 1 → 26."""
        result = compute_risk_score(
            ocr_avg_confidence=1.0,
            face_similarity=100.0,
            liveness_score=1.0,
            reconciliation_integrity=1.0,
            document_quality_avg=1.0,
            service_type="id_renewal",
            registry_match_score=0.0,
        )
        assert result["risk_score"] == pytest.approx(26.0)
        assert result["breakdown"]["registry_risk"] == 100.0
