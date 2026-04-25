"""Real-document accuracy harness for the OCR + Face pipeline.

Reads a manifest describing a folder of real (or sample) documents with
ground-truth field values and selfie/reference pairs, pushes them into
the running OCR + Face services via the shared uploads volume, and
reports per-field accuracy + face similarity.

Usage:
    # 1. Drop docs into evaluation/real_samples/<case_id>/
    # 2. Write evaluation/real_samples/manifest.yaml (see template below)
    # 3. Make sure docker compose is up (gateway, ocr, face)
    # 4. python scripts/test_real_docs.py evaluation/real_samples/manifest.yaml

Manifest format (YAML):

    cases:
      - case_id: sample_01
        documents:
          - path: sample_01/old_id_front.jpg
            document_type: old_id_front
            expected:
              national_id: "1234567"
              full_name: "Mohamed Saad"
              date_of_birth: "1990-05-12"
          - path: sample_01/passport_bio.jpg
            document_type: passport_bio
            expected:
              passport_number: "LR1234567"
              date_of_birth: "1990-05-12"
        face:
          selfie: sample_01/selfie.jpg
          reference: sample_01/old_id_front.jpg

The harness copies each file into the `uploads` Docker volume (via
`docker compose cp`) so the OCR/Face containers can read them at
`/app/uploads/...`.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

try:
    import yaml
except ImportError:
    print("PyYAML required: pip install pyyaml", file=sys.stderr)
    sys.exit(1)


OCR_URL = "http://localhost:8001/api/v1/ocr/process"
FACE_URL = "http://localhost:8002/api/v1/face/verify"
CONTAINER_UPLOAD_DIR = "/app/uploads/real_tests"


@dataclass
class FieldResult:
    field: str
    expected: str
    actual: str
    confidence: float
    match: bool


def _run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(
            f"Command failed: {' '.join(cmd)}\nstdout: {r.stdout}\nstderr: {r.stderr}"
        )


def copy_to_uploads_volume(local_path: Path, service_name: str) -> str:
    """Copy a local file into the shared uploads volume via the given
    compose *service* (not container) name.

    Returns the in-container path. Uses a safe filename (parent-prefixed)
    so files from different case folders don't collide.
    """
    safe_name = f"{local_path.parent.name}__{local_path.name}"
    container_path = f"{CONTAINER_UPLOAD_DIR}/{safe_name}"
    _run(["docker", "compose", "exec", "-T", service_name,
          "mkdir", "-p", CONTAINER_UPLOAD_DIR])
    _run(["docker", "compose", "cp", str(local_path),
          f"{service_name}:{container_path}"])
    return container_path


def normalize(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip().lower().replace(" ", "")


def compare_fields(expected: dict, extracted: dict, confidences: dict) -> list[FieldResult]:
    results = []
    for field, exp_val in expected.items():
        actual = extracted.get(field, "")
        match = normalize(actual) == normalize(exp_val)
        results.append(
            FieldResult(
                field=field,
                expected=str(exp_val),
                actual=str(actual or "<missing>"),
                confidence=float(confidences.get(field, 0.0)),
                match=match,
            )
        )
    return results


def run_ocr(container_path: str, document_type: str) -> dict:
    payload = {
        "document_id": f"real-test-{int(time.time()*1000)}",
        "file_path": container_path,
        "document_type": document_type,
    }
    r = httpx.post(OCR_URL, json=payload, timeout=60.0)
    r.raise_for_status()
    return r.json()


def run_face(selfie_path: str, reference_path: str) -> dict:
    payload = {
        "case_id": f"real-test-{int(time.time()*1000)}",
        "selfie_path": selfie_path,
        "reference_path": reference_path,
    }
    r = httpx.post(FACE_URL, json=payload, timeout=60.0)
    r.raise_for_status()
    return r.json()


def print_case_report(case_id: str, doc_results: list, face_result: dict | None) -> dict:
    print(f"\n{'='*70}\nCASE: {case_id}\n{'='*70}")
    totals = {"fields": 0, "matched": 0}
    for doc_path, doc_type, ocr_meta, field_results in doc_results:
        print(f"\n  [{doc_type}]  {doc_path}")
        confs = [c for c in ocr_meta.get("confidence_scores", {}).values() if c > 0]
        overall = (sum(confs) / len(confs)) if confs else 0.0
        print(f"    overall_confidence={overall:.2f}  "
              f"quality={ocr_meta.get('quality', {}).get('is_readable')}  "
              f"retake={ocr_meta.get('retake_required')}")
        if ocr_meta.get("quality", {}).get("issues"):
            print(f"    quality_issues: {ocr_meta['quality']['issues']}")
        for fr in field_results:
            mark = "✓" if fr.match else "✗"
            print(f"    {mark} {fr.field:20s} expected={fr.expected:25s} "
                  f"actual={fr.actual:25s} conf={fr.confidence:.2f}")
            totals["fields"] += 1
            if fr.match:
                totals["matched"] += 1
        if ocr_meta.get("mrz"):
            mrz = ocr_meta["mrz"]
            print(f"    MRZ: checks_passed={mrz.get('all_checks_passed')} "
                  f"doc={mrz.get('passport_number')} dob={mrz.get('date_of_birth')} "
                  f"name={mrz.get('surname')},{mrz.get('given_names')}")

    if face_result:
        print(f"\n  [face]")
        print(f"    similarity={face_result.get('similarity_score', 0):.3f}  "
              f"liveness={face_result.get('liveness_score', 0):.3f}  "
              f"decision={face_result.get('decision')}")

    acc = (totals["matched"] / totals["fields"]) if totals["fields"] else 0
    print(f"\n  >> field accuracy: {totals['matched']}/{totals['fields']} ({acc:.0%})")
    return {"case_id": case_id, "matched": totals["matched"], "total": totals["fields"],
            "face": face_result}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("manifest", type=Path, help="Path to manifest.yaml")
    ap.add_argument("--ocr-container", default="ocr",
                    help="docker compose *service name* for OCR (not container id)")
    ap.add_argument("--face-container", default="face",
                    help="docker compose *service name* for Face")
    ap.add_argument("--json-out", type=Path, help="Write summary JSON here")
    args = ap.parse_args()

    manifest = yaml.safe_load(args.manifest.read_text())
    base_dir = args.manifest.parent

    summary = []
    for case in manifest.get("cases", []):
        case_id = case["case_id"]
        doc_results = []
        for doc in case.get("documents", []):
            local = (base_dir / doc["path"]).resolve()
            if not local.exists():
                print(f"  SKIP (missing file): {local}", file=sys.stderr)
                continue
            container_path = copy_to_uploads_volume(local, args.ocr_container)
            # Face service reads the same shared volume, so the path is valid for both.
            try:
                ocr = run_ocr(container_path, doc["document_type"])
            except httpx.HTTPError as e:
                print(f"  OCR FAILED for {local}: {e}", file=sys.stderr)
                continue
            field_results = compare_fields(
                doc.get("expected", {}),
                ocr.get("extracted_fields", {}),
                ocr.get("confidence_scores", {}),
            )
            doc_results.append((doc["path"], doc["document_type"], ocr, field_results))

        face_result = None
        if case.get("face"):
            selfie = (base_dir / case["face"]["selfie"]).resolve()
            reference = (base_dir / case["face"]["reference"]).resolve()
            if selfie.exists() and reference.exists():
                selfie_c = copy_to_uploads_volume(selfie, args.face_container)
                ref_c = copy_to_uploads_volume(reference, args.face_container)
                try:
                    face_result = run_face(selfie_c, ref_c)
                except httpx.HTTPError as e:
                    print(f"  FACE FAILED: {e}", file=sys.stderr)

        summary.append(print_case_report(case_id, doc_results, face_result))

    print(f"\n{'='*70}\nAGGREGATE\n{'='*70}")
    total_matched = sum(s["matched"] for s in summary)
    total_fields = sum(s["total"] for s in summary)
    acc = (total_matched / total_fields) if total_fields else 0
    print(f"Field accuracy across all cases: {total_matched}/{total_fields} ({acc:.0%})")

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(summary, indent=2, default=str))
        print(f"Wrote {args.json_out}")


if __name__ == "__main__":
    main()
