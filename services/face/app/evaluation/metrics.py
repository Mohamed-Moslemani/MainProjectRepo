"""Face verification evaluation metrics - FAR, FRR, liveness attack detection."""

from dataclasses import dataclass, field


@dataclass
class FaceMetrics:
    # Face comparison
    true_accepts: int = 0       # genuine pair correctly accepted
    false_accepts: int = 0      # impostor pair incorrectly accepted
    true_rejects: int = 0       # impostor pair correctly rejected
    false_rejects: int = 0      # genuine pair incorrectly rejected
    manual_reviews: int = 0     # sent to manual review

    # Liveness
    live_correct: int = 0       # real face correctly detected as live
    live_incorrect: int = 0     # real face incorrectly flagged as spoof
    spoof_correct: int = 0      # spoof correctly detected
    spoof_incorrect: int = 0    # spoof incorrectly accepted as live

    # Latency
    latencies_ms: list[float] = field(default_factory=list)
    total_processed: int = 0

    @property
    def far(self) -> float:
        """False Accept Rate - fraction of impostors incorrectly accepted."""
        denom = self.false_accepts + self.true_rejects
        return self.false_accepts / denom if denom > 0 else 0.0

    @property
    def frr(self) -> float:
        """False Reject Rate - fraction of genuine users incorrectly rejected."""
        denom = self.false_rejects + self.true_accepts
        return self.false_rejects / denom if denom > 0 else 0.0

    @property
    def liveness_attack_detection_rate(self) -> float:
        """Fraction of spoof attacks correctly detected."""
        denom = self.spoof_correct + self.spoof_incorrect
        return self.spoof_correct / denom if denom > 0 else 0.0

    @property
    def liveness_false_rejection_rate(self) -> float:
        """Fraction of real faces incorrectly flagged as spoof."""
        denom = self.live_correct + self.live_incorrect
        return self.live_incorrect / denom if denom > 0 else 0.0

    @property
    def manual_review_rate(self) -> float:
        return self.manual_reviews / self.total_processed if self.total_processed > 0 else 0.0

    @property
    def latency_p50(self) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        return s[len(s) // 2]

    @property
    def latency_p95(self) -> float:
        if not self.latencies_ms:
            return 0.0
        s = sorted(self.latencies_ms)
        return s[min(int(len(s) * 0.95), len(s) - 1)]

    def record_comparison(
        self,
        decision: str,
        is_genuine_pair: bool,
        latency_ms: float,
    ):
        self.total_processed += 1
        self.latencies_ms.append(latency_ms)

        if decision == "manual_review":
            self.manual_reviews += 1
            return

        accepted = decision == "pass"

        if is_genuine_pair:
            if accepted:
                self.true_accepts += 1
            else:
                self.false_rejects += 1
        else:
            if accepted:
                self.false_accepts += 1
            else:
                self.true_rejects += 1

    def record_liveness(self, predicted_live: bool, actually_live: bool):
        if actually_live:
            if predicted_live:
                self.live_correct += 1
            else:
                self.live_incorrect += 1
        else:
            if not predicted_live:
                self.spoof_correct += 1
            else:
                self.spoof_incorrect += 1

    def report(self) -> dict:
        return {
            "far": round(self.far, 6),
            "frr": round(self.frr, 6),
            "liveness_attack_detection_rate": round(self.liveness_attack_detection_rate, 4),
            "liveness_false_rejection_rate": round(self.liveness_false_rejection_rate, 4),
            "manual_review_rate": round(self.manual_review_rate, 4),
            "latency_p50_ms": round(self.latency_p50, 1),
            "latency_p95_ms": round(self.latency_p95, 1),
            "total_processed": self.total_processed,
        }
