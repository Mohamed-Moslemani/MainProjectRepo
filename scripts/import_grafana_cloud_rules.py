#!/usr/bin/env python3
"""Sync local Prometheus rule files to Grafana Cloud Mimir Ruler.

The Mimir Ruler API takes one rule *group* per POST, scoped to a
namespace. We pick the namespace from the local file basename so the
Grafana Cloud UI groups things sensibly:

  monitoring/prometheus/alerts.yml          → namespace `alerts`
  monitoring/prometheus/drift_alerts.yml    → namespace `drift_alerts`
  monitoring/prometheus/recording_rules.yml → namespace `recording_rules`

Reads:
  GRAFANA_CLOUD_PROM_URL          — same value as remote_write URL
                                    (e.g. https://prometheus-prod-58-...
                                    .grafana.net/api/prom/push)
                                    The /api/prom/push suffix is
                                    rewritten to /api/prom/rules/<ns>.
  GRAFANA_CLOUD_PROM_USER         — numeric instance ID (Basic auth user)
  GRAFANA_CLOUD_PROM_API_KEY      — token (Basic auth password) with
                                    metrics:write scope.

Idempotent: each POST replaces the entire group at <namespace>/<group_name>.
Re-run after editing local YAML to push updates.
"""
from __future__ import annotations

import base64
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    import yaml  # PyYAML is already a project dep
except ImportError:
    sys.exit("PyYAML missing. Run inside a service container or `pip install pyyaml`.")

PROM_URL = os.environ.get("GRAFANA_CLOUD_PROM_URL", "").rstrip("/")
USER = os.environ.get("GRAFANA_CLOUD_PROM_USER", "").strip()
TOKEN = os.environ.get("GRAFANA_CLOUD_PROM_API_KEY", "").strip().strip('"')

if not PROM_URL or not USER or not TOKEN:
    sys.exit(
        "Missing env. Set:\n"
        "  GRAFANA_CLOUD_PROM_URL=<remote_write URL>\n"
        "  GRAFANA_CLOUD_PROM_USER=<instance ID>\n"
        "  GRAFANA_CLOUD_PROM_API_KEY=<token>\n"
    )

# Convert the remote_write push URL into the rules base:
#   https://prometheus-prod-58-….grafana.net/api/prom/push
#   →
#   https://prometheus-prod-58-….grafana.net/api/prom/rules
RULES_BASE = PROM_URL.rsplit("/", 1)[0] + "/rules"

AUTH = "Basic " + base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()

PROM_DIR = Path(__file__).resolve().parents[1] / "monitoring" / "prometheus"
RULE_FILES = ["alerts.yml", "drift_alerts.yml", "recording_rules.yml"]


def post_group(namespace: str, group: dict) -> tuple[bool, str]:
    body = yaml.safe_dump(group, sort_keys=False).encode()
    url = f"{RULES_BASE}/{namespace}"
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": AUTH,
            "Content-Type": "application/yaml",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return True, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
    except urllib.error.URLError as e:
        return False, f"connection error: {e.reason}"


def main() -> int:
    failed = 0
    total = 0
    for fname in RULE_FILES:
        path = PROM_DIR / fname
        if not path.exists():
            print(f"⚠ {path} not found, skipping")
            continue

        ns = path.stem  # 'alerts', 'drift_alerts', 'recording_rules'
        doc = yaml.safe_load(path.read_text())
        groups = doc.get("groups", [])
        if not groups:
            print(f"⚠ {fname} has no groups")
            continue

        print(f"\n📂 {fname}  →  namespace `{ns}`  ({len(groups)} group(s))")
        for g in groups:
            total += 1
            ok, msg = post_group(ns, g)
            marker = "✓" if ok else "✗"
            rules_count = len(g.get("rules", []))
            print(f"  {marker} group {g['name']:35s}  ({rules_count} rules)  {msg}")
            if not ok:
                failed += 1

    print(f"\n{total - failed}/{total} groups synced.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
