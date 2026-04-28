"""Pre-seed citizen accounts for the locust baseline.

Signup is bcrypt-bound (cost 12 ≈ 100ms per call), so creating the
load-test accounts mid-run would dominate the latency histogram. We
do it once up front, idempotently — re-running is a no-op when the
emails already exist.

Usage:
    python load/seed_users.py --base http://localhost:8000 --count 20
"""

from __future__ import annotations

import argparse
import sys

import requests


def seed(base_url: str, count: int, password: str, template: str) -> int:
    created = 0
    for i in range(count):
        email = template.format(i=i)
        resp = requests.post(
            f"{base_url}/api/v1/auth/signup",
            json={
                "email": email,
                "password": password,
                "first_name": "Load",
                "last_name": f"Test{i}",
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            created += 1
        elif resp.status_code in (400, 409):
            # Already exists — fine.
            pass
        else:
            print(f"signup {email} → {resp.status_code} {resp.text[:200]}")
    print(f"seeded {created} new accounts ({count - created} already existed)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--count", type=int, default=20)
    ap.add_argument("--password", default="Loadtest!2026")
    ap.add_argument("--template", default="loadtest+{i}@docflow.local")
    args = ap.parse_args()
    return seed(args.base, args.count, args.password, args.template)


if __name__ == "__main__":
    sys.exit(main())
