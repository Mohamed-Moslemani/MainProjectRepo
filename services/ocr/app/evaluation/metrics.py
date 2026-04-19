"""OCR evaluation metrics - field-level accuracy, F1, latency tracking."""

from dataclasses import dataclass, field
import time


@dataclass
class OCRMetrics:
    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    field_exact_matches: int = 0
    field_total: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    retake_count: int = 0
    total_processed: int = 0

    @property
    def precision(self) -> float:
        denom = self.true_positives + self.false_positives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def recall(self) -> float:
        denom = self.true_positives + self.false_negatives
        return self.true_positives / denom if denom > 0 else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) > 0 else 0.0

    @property
    def field_accuracy(self) -> float:
        return self.field_exact_matches / self.field_total if self.field_total > 0 else 0.0

    @property
    def latency_p50(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_l = sorted(self.latencies_ms)
        idx = len(sorted_l) // 2
        return sorted_l[idx]

    @property
    def latency_p95(self) -> float:
        if not self.latencies_ms:
            return 0.0
        sorted_l = sorted(self.latencies_ms)
        idx = int(len(sorted_l) * 0.95)
        return sorted_l[min(idx, len(sorted_l) - 1)]

    @property
    def retake_rate(self) -> float:
        return self.retake_count / self.total_processed if self.total_processed > 0 else 0.0

    def record_result(
        self,
        predicted_fields: dict[str, str],
        ground_truth: dict[str, str],
        latency_ms: float,
        retake_required: bool,
    ):
        self.total_processed += 1
        self.latencies_ms.append(latency_ms)
        if retake_required:
            self.retake_count += 1

        all_keys = set(predicted_fields.keys()) | set(ground_truth.keys())
        for key in all_keys:
            self.field_total += 1
            pred = predicted_fields.get(key, "").strip().lower()
            truth = ground_truth.get(key, "").strip().lower()

            if pred and truth:
                if pred == truth:
                    self.true_positives += 1
                    self.field_exact_matches += 1
                else:
                    self.true_positives += 1  # field found but wrong value
            elif pred and not truth:
                self.false_positives += 1
            elif truth and not pred:
                self.false_negatives += 1

    def report(self) -> dict:
        return {
            "precision": round(self.precision, 4),
            "recall": round(self.recall, 4),
            "f1": round(self.f1, 4),
            "field_accuracy": round(self.field_accuracy, 4),
            "latency_p50_ms": round(self.latency_p50, 1),
            "latency_p95_ms": round(self.latency_p95, 1),
            "retake_rate": round(self.retake_rate, 4),
            "total_processed": self.total_processed,
        }
