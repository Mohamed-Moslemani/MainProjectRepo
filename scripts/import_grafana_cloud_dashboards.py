#!/usr/bin/env python3
"""Import every dashboard JSON under monitoring/grafana/dashboards/
into Grafana Cloud.

Reads:
  GRAFANA_CLOUD_URL   — e.g. https://mohamedmoslemani.grafana.net
  GRAFANA_CLOUD_TOKEN — service-account token with Editor role
                        (Grafana Cloud → Administration → Users and access
                         → Service accounts → Add → Add token)

Idempotent: each dashboard's `uid` field pins identity, and the
`overwrite: true` flag tells Grafana to update in place rather than
fail on conflict — so re-running this script reapplies the latest
local copy.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

URL = os.environ.get("GRAFANA_CLOUD_URL", "").rstrip("/")
TOKEN = os.environ.get("GRAFANA_CLOUD_TOKEN", "").strip()

if not URL or not TOKEN:
    sys.exit(
        "Missing env. Set:\n"
        "  GRAFANA_CLOUD_URL=https://<your-stack>.grafana.net\n"
        "  GRAFANA_CLOUD_TOKEN=<service-account-token>\n"
    )

DASHBOARDS_DIR = Path(__file__).resolve().parents[1] / "monitoring" / "grafana" / "dashboards"


def post_dashboard(path: Path) -> tuple[bool, str]:
    body = json.loads(path.read_text())
    body["id"] = None  # always create-or-update by uid, never by id
    payload = json.dumps({
        "dashboard": body,
        "overwrite": True,
        "folderUid": "",
        "message": f"imported from {path.name}",
    }).encode()

    req = urllib.request.Request(
        f"{URL}/api/dashboards/db",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            return True, f"{data.get('status', 'ok')} → {URL}{data.get('url', '')}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}"
    except urllib.error.URLError as e:
        return False, f"connection error: {e.reason}"


def main() -> int:
    files = sorted(DASHBOARDS_DIR.glob("*.json"))
    if not files:
        sys.exit(f"No dashboards found under {DASHBOARDS_DIR}")

    failed = 0
    for path in files:
        ok, msg = post_dashboard(path)
        marker = "✓" if ok else "✗"
        print(f"{marker} {path.name:40s}  {msg}")
        if not ok:
            failed += 1

    print(f"\n{len(files) - failed}/{len(files)} dashboards imported.")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
