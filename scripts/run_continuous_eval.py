"""Continuous evaluation: run the real-doc harness, push the score
to Prometheus.

Designed to be cron-triggered (or run by a Kubernetes CronJob /
GitHub Actions schedule). Every run:

  1. Reuses the existing manifest-driven harness in
     scripts/test_real_docs.py against a labelled set of real
     documents (the "golden set").
  2. Computes the aggregate field-accuracy score.
  3. Pushes the score to a Prometheus pushgateway as
     `docflow_eval_field_accuracy{harness="real_docs"}` so a
     Grafana panel can chart accuracy over time and an alert can
     fire when accuracy regresses below a floor.

Why pushgateway and not a /metrics scrape: the harness is a one-
shot job, not a long-lived service. Prometheus's pull model needs
a target that stays up; pushgateway is the standard short-lived-job
shim.

Usage:
    python scripts/run_continuous_eval.py \\
        --manifest evaluation/real_samples/manifest.yaml \\
        --pushgateway http://pushgateway:9091 \\
        --job docflow-real-doc-eval

If --pushgateway is omitted the score is printed to stdout (useful
for ad-hoc CI runs that only need the exit code).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--pushgateway", default="")
    ap.add_argument("--job", default="docflow-real-doc-eval")
    ap.add_argument(
        "--floor",
        type=float,
        default=0.0,
        help="Exit non-zero if aggregate accuracy < floor (e.g. 0.6 for 60%%).",
    )
    args = ap.parse_args()

    json_out = Path("/tmp/docflow-eval-summary.json")
    cmd = [
        sys.executable, "scripts/test_real_docs.py",
        str(args.manifest),
        "--json-out", str(json_out),
    ]
    print("running:", " ".join(cmd))
    subprocess.run(cmd, check=True)

    summary = json.loads(json_out.read_text())
    total_matched = sum(s["matched"] for s in summary)
    total_fields = sum(s["total"] for s in summary)
    accuracy = (total_matched / total_fields) if total_fields else 0.0

    print(f"aggregate field accuracy: {total_matched}/{total_fields} = {accuracy:.4f}")

    if args.pushgateway:
        # Push as a single Prometheus gauge with stable labels.
        # Anti-corruption layer in case prometheus_client isn't
        # installed in the eval runner — fall back to raw HTTP.
        body = (
            f"# TYPE docflow_eval_field_accuracy gauge\n"
            f'docflow_eval_field_accuracy{{harness="real_docs"}} {accuracy}\n'
            f"# TYPE docflow_eval_total_fields gauge\n"
            f'docflow_eval_total_fields{{harness="real_docs"}} {total_fields}\n'
            f"# TYPE docflow_eval_matched_fields gauge\n"
            f'docflow_eval_matched_fields{{harness="real_docs"}} {total_matched}\n'
        )
        import urllib.request
        url = f"{args.pushgateway.rstrip('/')}/metrics/job/{args.job}"
        req = urllib.request.Request(
            url, data=body.encode(), method="PUT",
            headers={"Content-Type": "text/plain"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            print("pushgateway:", resp.status)

    if args.floor and accuracy < args.floor:
        print(f"FAIL: accuracy {accuracy:.2%} below floor {args.floor:.2%}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
