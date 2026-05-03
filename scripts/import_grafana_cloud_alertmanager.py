#!/usr/bin/env python3
"""Sync the cloud-managed Alertmanager config to Grafana Cloud's
Mimir Alertmanager.

Reads:
  GRAFANA_CLOUD_ALERTMANAGER_URL  — base URL, e.g.
                                    https://alertmanager-prod-eu-central-0.grafana.net
                                    Find it on the stack details page →
                                    "Alertmanager" tile → "Configure".
  GRAFANA_CLOUD_PROM_USER         — same instance ID used for metrics
  GRAFANA_CLOUD_ALERTS_API_KEY    — token with `alerts:write` scope.
                                    Generated on the Alertmanager
                                    Details page. Falls back to
                                    GRAFANA_CLOUD_PROM_API_KEY if your
                                    Cloud Access Policy bundles both
                                    metrics:write + alerts:write.

  Optional secrets that get inlined into the YAML:
    SLACK_WEBHOOK_URL             — Slack incoming webhook URL
    PAGERDUTY_ROUTING_KEY         — PagerDuty Events API v2 routing key

Source file:
  monitoring/alertmanager/alertmanager.cloud.yml — env-var placeholders
  ${SLACK_WEBHOOK_URL} / ${PAGERDUTY_ROUTING_KEY} are substituted before
  upload, so the file itself stays in git without secrets.

Idempotent: each POST replaces the entire Alertmanager config for the
tenant. Re-run after editing the YAML to push updates.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import string
import sys
import urllib.error
import urllib.request
from pathlib import Path

# Force IPv4 — some hosts have an unreachable IPv6 route to Grafana
# Cloud's alertmanager subdomain and Python's urllib tries v6 first
# without happy-eyeballs fallback.
_orig_getaddrinfo = socket.getaddrinfo
socket.getaddrinfo = lambda host, port, family=0, *a, **kw: _orig_getaddrinfo(
    host, port, socket.AF_INET, *a, **kw
)

AM_URL = os.environ.get("GRAFANA_CLOUD_ALERTMANAGER_URL", "").rstrip("/")
# Alertmanager uses the *stack* ID for Basic auth, not the Prometheus
# instance ID. Override with GRAFANA_CLOUD_ALERTS_USER if it differs;
# otherwise fall back to the Prom user (works when stack==instance).
USER = (
    os.environ.get("GRAFANA_CLOUD_ALERTS_USER", "").strip()
    or os.environ.get("GRAFANA_CLOUD_PROM_USER", "").strip()
)
# Prefer the alerts-scoped token; fall back to the metrics one if a
# single token covers both scopes.
TOKEN = (
    os.environ.get("GRAFANA_CLOUD_ALERTS_API_KEY", "").strip().strip('"')
    or os.environ.get("GRAFANA_CLOUD_PROM_API_KEY", "").strip().strip('"')
)

if not AM_URL or not USER or not TOKEN:
    sys.exit(
        "Missing env. Set:\n"
        "  GRAFANA_CLOUD_ALERTMANAGER_URL=https://alertmanager-prod-<region>.grafana.net\n"
        "  GRAFANA_CLOUD_PROM_USER=<instance ID>\n"
        "  GRAFANA_CLOUD_ALERTS_API_KEY=<token with alerts:write>\n"
    )

CONFIG_PATH = (
    Path(__file__).resolve().parents[1]
    / "monitoring" / "alertmanager" / "alertmanager.cloud.yml"
)

if not CONFIG_PATH.exists():
    sys.exit(f"Source config not found: {CONFIG_PATH}")

# Substitute ${VAR} placeholders. Missing vars → empty string with a
# warning, so the upload still succeeds for receivers you HAVE set up.
raw = CONFIG_PATH.read_text()
template = string.Template(raw)
subs = {
    "SLACK_WEBHOOK_URL": os.environ.get("SLACK_WEBHOOK_URL", ""),
    "PAGERDUTY_ROUTING_KEY": os.environ.get("PAGERDUTY_ROUTING_KEY", ""),
}
for key, val in subs.items():
    if not val:
        print(f"⚠ {key} is empty — receiver using it will be replaced with a no-op.")
config_yaml = template.safe_substitute(subs)

# Mimir's alertmanager validator rejects empty routing_key /
# api_url. When the user hasn't set those secrets yet, surgically
# rewrite the config so empty receivers become a no-op `null`
# receiver instead of failing the whole upload. Alerts still fire
# server-side and surface in Grafana → Alerting → Active alerts;
# they just don't notify externally until the secrets are added.
import yaml as _yaml  # PyYAML — listed in requirements above

cfg = _yaml.safe_load(config_yaml)
if isinstance(cfg, dict):
    receivers = cfg.get("receivers") or []
    healthy_names: set[str] = set()
    for r in receivers:
        # Drop pagerduty entries with empty routing_key
        pd = [x for x in (r.get("pagerduty_configs") or [])
              if (x.get("routing_key") or "").strip()]
        if pd:
            r["pagerduty_configs"] = pd
        else:
            r.pop("pagerduty_configs", None)

        # Drop slack entries with empty api_url
        sl = [x for x in (r.get("slack_configs") or [])
              if (x.get("api_url") or "").strip()]
        if sl:
            r["slack_configs"] = sl
        else:
            r.pop("slack_configs", None)

        if any(k.endswith("_configs") and r.get(k) for k in list(r.keys())):
            healthy_names.add(r["name"])

    # Replace any receiver that lost all of its sub-configs with a
    # null receiver (Alertmanager treats `name` alone as a no-op).
    for r in receivers:
        if r["name"] not in healthy_names:
            for k in list(r.keys()):
                if k.endswith("_configs"):
                    r.pop(k, None)

    config_yaml = _yaml.safe_dump(cfg, sort_keys=False)

payload = json.dumps({
    "template_files": {},
    "alertmanager_config": config_yaml,
}).encode()

auth = "Basic " + base64.b64encode(f"{USER}:{TOKEN}".encode()).decode()

req = urllib.request.Request(
    f"{AM_URL}/api/v1/alerts",
    data=payload,
    method="POST",
    headers={
        "Authorization": auth,
        "Content-Type": "application/json",
    },
)

try:
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode(errors="replace")
        print(f"✓ Alertmanager config synced  (HTTP {resp.status})  {body[:200]}")
except urllib.error.HTTPError as e:
    err = e.read().decode(errors="replace")
    sys.exit(f"✗ HTTP {e.code}: {err[:500]}")
except urllib.error.URLError as e:
    sys.exit(f"✗ connection error: {e.reason}")
