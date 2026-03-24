"""Evaluation runner - runs OCR and Face eval suites against test datasets.

Usage:
    python -m evaluation.runner --service ocr --dataset eval_data/ocr/
    python -m evaluation.runner --service face --dataset eval_data/face/
    python -m evaluation.runner --service e2e --dataset eval_data/e2e/

Dataset format:
    For OCR:  eval_data/ocr/{sample_id}/image.jpg + ground_truth.json
    For Face: eval_data/face/{sample_id}/selfie.jpg + reference.jpg + label.json
"""

import argparse
import json
import os
import sys
import time
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.ocr.app.evaluation.metrics import OCRMetrics
from services.face.app.evaluation.metrics import FaceMetrics


def run_ocr_eval(dataset_dir: str, ocr_url: str) -> dict:
    metrics = OCRMetrics()

    for sample_id in sorted(os.listdir(dataset_dir)):
        sample_dir = os.path.join(dataset_dir, sample_id)
        if not os.path.isdir(sample_dir):
            continue

        gt_path = os.path.join(sample_dir, "ground_truth.json")
        if not os.path.exists(gt_path):
            print(f"  Skipping {sample_id}: no ground_truth.json")
            continue

        with open(gt_path) as f:
            gt = json.load(f)

        # Find image file
        image_path = None
        for ext in ("jpg", "jpeg", "png", "webp"):
            candidate = os.path.join(sample_dir, f"image.{ext}")
            if os.path.exists(candidate):
                image_path = candidate
                break

        if not image_path:
            print(f"  Skipping {sample_id}: no image file found")
            continue

        print(f"  Processing {sample_id}...")
        start = time.time()

        response = httpx.post(
            f"{ocr_url}/api/v1/ocr/process",
            json={
                "document_id": sample_id,
                "file_path": image_path,
                "document_type": gt.get("document_type", "national_id"),
            },
            timeout=30.0,
        )

        latency_ms = (time.time() - start) * 1000

        if response.status_code != 200:
            print(f"  ERROR: {response.status_code} - {response.text}")
            continue

        result = response.json()
        metrics.record_result(
            predicted_fields=result.get("extracted_fields", {}),
            ground_truth=gt.get("fields", {}),
            latency_ms=latency_ms,
            retake_required=result.get("retake_required", False),
        )

    return metrics.report()


def run_face_eval(dataset_dir: str, face_url: str) -> dict:
    metrics = FaceMetrics()

    for sample_id in sorted(os.listdir(dataset_dir)):
        sample_dir = os.path.join(dataset_dir, sample_id)
        if not os.path.isdir(sample_dir):
            continue

        label_path = os.path.join(sample_dir, "label.json")
        if not os.path.exists(label_path):
            print(f"  Skipping {sample_id}: no label.json")
            continue

        with open(label_path) as f:
            label = json.load(f)

        selfie_path = os.path.join(sample_dir, "selfie.jpg")
        reference_path = os.path.join(sample_dir, "reference.jpg")

        if not os.path.exists(selfie_path) or not os.path.exists(reference_path):
            print(f"  Skipping {sample_id}: missing images")
            continue

        print(f"  Processing {sample_id}...")
        start = time.time()

        response = httpx.post(
            f"{face_url}/api/v1/face/verify",
            json={
                "case_id": sample_id,
                "selfie_path": selfie_path,
                "reference_path": reference_path,
            },
            timeout=30.0,
        )

        latency_ms = (time.time() - start) * 1000

        if response.status_code != 200:
            print(f"  ERROR: {response.status_code} - {response.text}")
            continue

        result = response.json()

        metrics.record_comparison(
            decision=result["decision"],
            is_genuine_pair=label.get("is_genuine", True),
            latency_ms=latency_ms,
        )

        metrics.record_liveness(
            predicted_live=result.get("liveness_passed", False),
            actually_live=label.get("is_live", True),
        )

    return metrics.report()


def run_e2e_eval(dataset_dir: str, gateway_url: str) -> dict:
    """End-to-end evaluation: measure full pipeline latency and success rate."""
    results = {
        "total": 0,
        "successful": 0,
        "failed": 0,
        "latencies_ms": [],
        "resubmission_count": 0,
    }

    for sample_id in sorted(os.listdir(dataset_dir)):
        sample_dir = os.path.join(dataset_dir, sample_id)
        if not os.path.isdir(sample_dir):
            continue

        config_path = os.path.join(sample_dir, "config.json")
        if not os.path.exists(config_path):
            continue

        with open(config_path) as f:
            config = json.load(f)

        results["total"] += 1
        start = time.time()

        try:
            # Register + login
            reg_resp = httpx.post(f"{gateway_url}/api/v1/auth/register", json={
                "email": f"eval_{sample_id}@test.com",
                "password": "testpass123",
                "full_name": config.get("full_name", "Test User"),
            }, timeout=10.0)

            login_resp = httpx.post(f"{gateway_url}/api/v1/auth/login", json={
                "email": f"eval_{sample_id}@test.com",
                "password": "testpass123",
            }, timeout=10.0)

            token = login_resp.json()["access_token"]
            headers = {"Authorization": f"Bearer {token}"}

            # Create case
            case_resp = httpx.post(f"{gateway_url}/api/v1/cases", json={
                "service_type": config.get("service_type", "id_new"),
            }, headers=headers, timeout=10.0)
            case_id = case_resp.json()["id"]

            # Upload documents
            for doc in config.get("documents", []):
                doc_path = os.path.join(sample_dir, doc["filename"])
                if os.path.exists(doc_path):
                    with open(doc_path, "rb") as f:
                        httpx.post(
                            f"{gateway_url}/api/v1/cases/{case_id}/documents",
                            data={"document_type": doc["type"]},
                            files={"file": (doc["filename"], f, "image/jpeg")},
                            headers=headers,
                            timeout=30.0,
                        )

            # Submit case
            submit_resp = httpx.post(
                f"{gateway_url}/api/v1/cases/{case_id}/submit",
                headers=headers,
                timeout=60.0,
            )

            latency_ms = (time.time() - start) * 1000
            results["latencies_ms"].append(latency_ms)

            if submit_resp.status_code == 200:
                results["successful"] += 1
            else:
                results["failed"] += 1

        except Exception as e:
            results["failed"] += 1
            print(f"  ERROR on {sample_id}: {e}")

    # Calculate latency stats
    if results["latencies_ms"]:
        sorted_l = sorted(results["latencies_ms"])
        results["latency_p50_ms"] = round(sorted_l[len(sorted_l) // 2], 1)
        results["latency_p95_ms"] = round(sorted_l[min(int(len(sorted_l) * 0.95), len(sorted_l) - 1)], 1)

    results["success_rate"] = (
        results["successful"] / results["total"] if results["total"] > 0 else 0.0
    )
    del results["latencies_ms"]
    return results


def main():
    parser = argparse.ArgumentParser(description="DocFlow Evaluation Runner")
    parser.add_argument("--service", choices=["ocr", "face", "e2e"], required=True)
    parser.add_argument("--dataset", required=True, help="Path to evaluation dataset directory")
    parser.add_argument("--url", default=None, help="Service URL override")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    default_urls = {
        "ocr": "http://localhost:8001",
        "face": "http://localhost:8002",
        "e2e": "http://localhost:8000",
    }
    url = args.url or default_urls[args.service]

    print(f"Running {args.service} evaluation...")
    print(f"  Dataset: {args.dataset}")
    print(f"  Service URL: {url}")

    if args.service == "ocr":
        report = run_ocr_eval(args.dataset, url)
    elif args.service == "face":
        report = run_face_eval(args.dataset, url)
    else:
        report = run_e2e_eval(args.dataset, url)

    print("\n--- Evaluation Report ---")
    print(json.dumps(report, indent=2))

    if args.output:
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
