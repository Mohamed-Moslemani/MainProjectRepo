"""Locust baseline for DocFlow gateway.

Goal of this file: establish a *repeatable* load profile that exercises
the hot read paths and the auth + case-creation write paths under
realistic citizen behaviour, so we can catch regressions before they
ship. It is intentionally not an end-to-end pipeline test (those
already exist in evaluation/); the AI services are presumed to be
running in mock mode here.

Run locally against a compose stack:

    OCR_MOCK_MODE=true FACE_MOCK_MODE=true docker compose up -d
    locust -f load/locustfile.py --host=http://localhost:8000

Run headless for a CI smoke baseline:

    locust -f load/locustfile.py --host=http://localhost:8000 \
           --headless -u 50 -r 5 -t 2m --csv=load/baseline

The CSV output is what the SLO gate compares against; see
load/check_slo.py.

User mix (weights are arbitrary but reflect real traffic shape):

  - read-heavy citizen browsing list of cases  : 10
  - login + create draft case                  :  3
  - admin pulling case queue                   :  1

The login flow uses a pool of pre-seeded accounts so we don't
hammer bcrypt with new signups at every spawn (signup is the most
expensive single endpoint and will dominate the histogram if used
naively).
"""

from __future__ import annotations

import os
import random
import uuid
from typing import Optional

from locust import HttpUser, between, events, task


# ──────────────────────────────────────────────────────────────────
#  Test accounts. Pre-create these via evaluation/runner.py or the
#  signup endpoint before running the load test; bcrypt cost ~12
#  means signing up 100 users mid-test would skew the latency
#  histogram badly.
# ──────────────────────────────────────────────────────────────────
SEED_USER_COUNT = int(os.getenv("LOAD_SEED_USERS", "20"))
SEED_PASSWORD = os.getenv("LOAD_SEED_PASSWORD", "Loadtest!2026")
SEED_EMAIL_TEMPLATE = os.getenv(
    "LOAD_SEED_EMAIL_TEMPLATE", "loadtest+{i}@docflow.local"
)


def _seed_email(i: int) -> str:
    return SEED_EMAIL_TEMPLATE.format(i=i)


class CitizenUser(HttpUser):
    """Simulates a logged-in citizen browsing their cases."""

    weight = 10
    wait_time = between(1, 4)

    token: Optional[str] = None

    def on_start(self) -> None:
        idx = random.randint(0, SEED_USER_COUNT - 1)
        with self.client.post(
            "/api/v1/auth/login",
            json={"email": _seed_email(idx), "password": SEED_PASSWORD},
            name="auth:login",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self.token = resp.json().get("access_token")
            else:
                # Don't crash the user — let it run without auth, the
                # endpoints will 401 and we'll see that in the chart.
                resp.failure(f"login failed: {resp.status_code}")

    def _auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    @task(8)
    def list_my_cases(self) -> None:
        self.client.get(
            "/api/v1/cases", headers=self._auth(), name="cases:list"
        )

    @task(2)
    def health(self) -> None:
        # Liveness ping is what an LB would do; cheap to verify it
        # stays under a few ms even at high RPS.
        self.client.get("/health/ready", name="health:ready")

    @task(1)
    def create_draft_case(self) -> None:
        if not self.token:
            return
        self.client.post(
            "/api/v1/cases",
            headers={
                **self._auth(),
                "Idempotency-Key": str(uuid.uuid4()),
            },
            json={
                "service_type": random.choice(
                    ["id_renewal", "passport_renewal", "id_new"]
                ),
            },
            name="cases:create_draft",
        )


class AdminUser(HttpUser):
    """Clerk pulling the review queue."""

    weight = 1
    wait_time = between(2, 6)

    token: Optional[str] = None

    def on_start(self) -> None:
        email = os.getenv("LOAD_ADMIN_EMAIL", "admin@docflow.local")
        password = os.getenv("LOAD_ADMIN_PASSWORD", SEED_PASSWORD)
        with self.client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": password},
            name="auth:login_admin",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                self.token = resp.json().get("access_token")
            else:
                resp.failure("admin login failed (seed an admin user first)")

    @task
    def queue(self) -> None:
        if not self.token:
            return
        self.client.get(
            "/api/v1/admin/cases?status=RISK_EVALUATED",
            headers={"Authorization": f"Bearer {self.token}"},
            name="admin:queue",
        )


# ──────────────────────────────────────────────────────────────────
#  SLO assertions. Run inline at test end so the locust process
#  exits non-zero if the baseline regressed; the deploy pipeline's
#  load-test step is gated on this exit code.
# ──────────────────────────────────────────────────────────────────
P95_BUDGET_MS = {
    "auth:login": 800,
    "cases:list": 250,
    "cases:create_draft": 500,
    "health:ready": 50,
    "admin:queue": 400,
}
ERROR_RATE_BUDGET = 0.01  # 1%


@events.quitting.add_listener
def _enforce_slo(environment, **_kwargs):
    failed = []
    stats = environment.stats
    for name, budget_ms in P95_BUDGET_MS.items():
        entry = stats.get(name, "GET") if "GET" in name else None
        # Locust keys stats by (name, method). We registered names
        # without methods, so iterate through entries instead.
    for entry in stats.entries.values():
        budget = P95_BUDGET_MS.get(entry.name)
        if budget is None:
            continue
        p95 = entry.get_response_time_percentile(0.95)
        if p95 > budget:
            failed.append(
                f"{entry.name} p95 {p95:.0f}ms > budget {budget}ms"
            )

    total = stats.total
    if total.num_requests > 0:
        err_rate = total.num_failures / total.num_requests
        if err_rate > ERROR_RATE_BUDGET:
            failed.append(
                f"error rate {err_rate:.2%} > budget {ERROR_RATE_BUDGET:.2%}"
            )

    if failed:
        print("SLO FAIL:")
        for line in failed:
            print(f"  - {line}")
        environment.process_exit_code = 1
    else:
        print("SLO PASS")
