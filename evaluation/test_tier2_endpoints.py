"""Smoke E2E for the Tier 2 frontend-supporting endpoints.

Covers the gateway endpoints the new SPA pages depend on:

  - GET  /api/v1/reference/{sects,gdgs-centres,passport-validity,renewal-reasons}
  - PATCH /api/v1/auth/me                  (religious_sect)
  - PATCH /api/v1/cases/{id}/declared-fields
        + verifies /required-documents picks up reason-gated docs
        + verifies passport_validity_years is persisted
  - GET  /api/v1/appointments/centres
  - GET  /api/v1/appointments/centres/{id}/slots

Mirrors the test_passport_renewal_e2e.py pattern (uses psycopg2 to
flip email_verified post-register). No real provider calls; mock
mode is fine.
"""

from __future__ import annotations

import sys
import time
import uuid

import psycopg2
import requests


BASE = "http://localhost:8000"
API = f"{BASE}/api/v1"
DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

EMAIL = f"t2e2e+{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "Tier2Test!2026"

PASS, FAIL = 0, 0


def check(name: str, cond: bool, hint: str = ""):
    global PASS, FAIL
    if cond:
        print(f"  [PASS] {name}")
        PASS += 1
    else:
        print(f"  [FAIL] {name}{(' — ' + hint) if hint else ''}")
        FAIL += 1


def main() -> int:
    print("=" * 60)
    print("  Tier 2 endpoints E2E")
    print(f"  Target: {BASE}")
    print("=" * 60)

    # Wait for gateway
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            if requests.get(f"{BASE}/health", timeout=2).status_code == 200:
                break
        except requests.ConnectionError:
            time.sleep(1)
    else:
        sys.exit("[FAIL] gateway not ready")

    # ── Reference endpoints (unauthenticated) ─────────────────────
    print("\n--- Reference data ---")
    r = requests.get(f"{API}/reference/sects")
    check("GET /reference/sects → 200", r.status_code == 200)
    sects = r.json().get("sects", [])
    check("18 sects", len(sects) == 18, f"got {len(sects)}")
    check("druze in sects", any(s["id"] == "druze" for s in sects))

    r = requests.get(f"{API}/reference/gdgs-centres")
    check("GET /reference/gdgs-centres → 200", r.status_code == 200)
    centres = r.json().get("centres", [])
    check("9 centres", len(centres) == 9, f"got {len(centres)}")

    r = requests.get(f"{API}/reference/passport-validity")
    check("GET /reference/passport-validity → 200", r.status_code == 200)
    options = r.json().get("options", [])
    years = sorted(o["years"] for o in options)
    check("validity tiers = [1,3,5,10]", years == [1, 3, 5, 10])
    one_year = next(o for o in options if o["years"] == 1)
    check("1-year fee = 5000c", one_year["fee_cents"] == 5000)

    r = requests.get(f"{API}/reference/renewal-reasons")
    check("GET /reference/renewal-reasons → 200", r.status_code == 200)
    reasons = r.json().get("reasons", [])
    lost = next((x for x in reasons if x["id"] == "lost"), None)
    check("lost requires police_report",
          lost and "police_report" in lost.get("extra_docs", []))

    # ── Register + login (verify via DB) ──────────────────────────
    print("\n--- Register/login ---")
    r = requests.post(f"{API}/auth/register", json={
        "email": EMAIL,
        "password": PASSWORD,
        "full_name": "Tier Two Tester",
        "father_name": "Ali",
        "mother_name": "Mariam",
        "date_of_birth": "1990-05-15",
        "place_of_birth": "Beirut",
        "gender": "male",
        "registry_number": "999/45",
        "registry_place": "Beirut",
    })
    check("register → 201", r.status_code == 201, r.text[:200])
    if r.status_code != 201:
        return 1
    user_id = r.json()["id"]

    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET email_verified=TRUE WHERE id=%s", (user_id,))
        conn.commit()

    r = requests.post(f"{API}/auth/login", json={"email": EMAIL, "password": PASSWORD})
    check("login → 200", r.status_code == 200, r.text[:200])
    if r.status_code != 200:
        return 1
    token = r.json()["access_token"]
    auth = {"Authorization": f"Bearer {token}"}

    # ── Religious sect on profile ─────────────────────────────────
    print("\n--- religious_sect on /auth/me ---")
    r = requests.get(f"{API}/auth/me", headers=auth)
    check("GET /auth/me → 200", r.status_code == 200)
    check("religious_sect field present", "religious_sect" in r.json())

    r = requests.patch(f"{API}/auth/me", headers=auth, json={"religious_sect": "druze"})
    check("PATCH religious_sect=druze → 200", r.status_code == 200, r.text[:200])
    check("religious_sect persisted", r.json().get("religious_sect") == "druze")

    r = requests.patch(f"{API}/auth/me", headers=auth, json={"religious_sect": "jedi"})
    check("invalid sect → 400", r.status_code == 400, r.text[:200])

    r = requests.patch(f"{API}/auth/me", headers=auth, json={"religious_sect": None})
    check("clear sect (None) → 200", r.status_code == 200)

    # ── PATCH declared-fields drives required-docs ────────────────
    print("\n--- PATCH declared-fields → required-docs reactivity ---")
    r = requests.post(f"{API}/cases", headers=auth, json={
        "service_type": "passport_renewal", "declared_fields": {},
    })
    check("create passport_renewal case → 201", r.status_code == 201, r.text[:200])
    if r.status_code != 201:
        return 1
    case_id = r.json()["id"]

    r = requests.get(f"{API}/cases/{case_id}/required-documents", headers=auth)
    base_docs = set(r.json().get("required_documents", []))
    check("base required docs has old_passport_data_page",
          "old_passport_data_page" in base_docs)
    check("base does NOT include police_report", "police_report" not in base_docs)

    r = requests.patch(
        f"{API}/cases/{case_id}/declared-fields",
        headers=auth,
        json={"renewal_reason": "lost", "passport_validity_years": 10},
    )
    check("PATCH declared-fields → 200", r.status_code == 200, r.text[:200])
    declared = r.json().get("declared_fields", {})
    check("renewal_reason persisted", declared.get("renewal_reason") == "lost")
    check("passport_validity_years persisted",
          declared.get("passport_validity_years") == 10)

    r = requests.get(f"{API}/cases/{case_id}/required-documents", headers=auth)
    docs_after = set(r.json().get("required_documents", []))
    check("required docs now include police_report",
          "police_report" in docs_after, f"got {sorted(docs_after)}")

    # name_change → court_ruling
    r = requests.patch(
        f"{API}/cases/{case_id}/declared-fields",
        headers=auth, json={"renewal_reason": "name_change"},
    )
    check("switch reason → name_change", r.status_code == 200)
    r = requests.get(f"{API}/cases/{case_id}/required-documents", headers=auth)
    docs_nc = set(r.json().get("required_documents", []))
    check("name_change requires court_ruling", "court_ruling" in docs_nc)
    check("police_report no longer required", "police_report" not in docs_nc)

    # ── Appointments listing ──────────────────────────────────────
    print("\n--- Appointments lookup (auth required for slots) ---")
    r = requests.get(f"{API}/appointments/centres")
    check("GET /appointments/centres → 200", r.status_code == 200)
    centres = r.json().get("centres", [])
    check("≥9 centres returned", len(centres) >= 9, f"got {len(centres)}")
    if centres:
        cid = centres[0]["id"]
        r = requests.get(f"{API}/appointments/centres/{cid}/slots", headers=auth)
        check("GET slots → 200", r.status_code == 200, r.text[:200])
        slots = r.json().get("slots", [])
        check("slots is list", isinstance(slots, list))

    # ── Cleanup ──────────────────────────────────────────────────
    with psycopg2.connect(DSN) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_logs WHERE user_id=%s", (user_id,))
        cur.execute("DELETE FROM email_verification_tokens WHERE user_id=%s", (user_id,))
        cur.execute("DELETE FROM password_reset_tokens WHERE user_id=%s", (user_id,))
        cur.execute("DELETE FROM refresh_tokens WHERE user_id=%s", (user_id,))
        cur.execute("DELETE FROM cases WHERE user_id=%s", (user_id,))
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))
        conn.commit()

    print("\n" + "=" * 60)
    print(f"  PASS={PASS}  FAIL={FAIL}")
    print("=" * 60)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
