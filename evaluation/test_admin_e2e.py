"""
End-to-end integration test for admin/clerk flows.

Tests:
  - Admin/clerk case listing and filtering
  - Status transitions by clerk (approve, reject, need_info)
  - Audit log entries
  - Role-based access control

Usage:
    1. docker compose --env-file .env.dev up -d --build
    2. python -m evaluation.test_admin_e2e
"""

import sys
import time
import uuid

import psycopg2
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"
DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

CITIZEN_EMAIL = f"citizen_{uuid.uuid4().hex[:8]}@example.com"
CLERK_EMAIL = f"clerk_{uuid.uuid4().hex[:8]}@example.com"
ADMIN_EMAIL = f"admin_{uuid.uuid4().hex[:8]}@example.com"
PASSWORD = "Str0ng!Pass#1"

# ── Helpers ───────────────────────────────────────────────────────────────────

def flush_rate_limits():
    """Clear Redis rate limit keys."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6380, db=0)
        r.flushdb()
    except Exception:
        pass


def wait_for_gateway(timeout: int = 60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/health", timeout=3)
            if r.status_code == 200:
                print("[OK] Gateway is healthy")
                return
        except requests.ConnectionError:
            pass
        time.sleep(2)
    sys.exit("[FAIL] Gateway did not become healthy in time")


def db_conn():
    return psycopg2.connect(DB_DSN)


def assert_eq(label, actual, expected):
    if actual != expected:
        sys.exit(f"[FAIL] {label}: expected {expected!r}, got {actual!r}")
    print(f"  [PASS] {label}")


def assert_status(label, resp, expected):
    if resp.status_code != expected:
        detail = ""
        try:
            detail = f" — {resp.json()}"
        except Exception:
            detail = f" — {resp.text[:200]}"
        sys.exit(f"[FAIL] {label}: expected {expected}, got {resp.status_code}{detail}")
    print(f"  [PASS] {label} -> {expected}")


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def create_user(email: str, role: str = "citizen") -> tuple:
    """Register, set role + verify in DB, login, return (token, user_id)."""
    flush_rate_limits()
    r = requests.post(f"{API}/auth/register", json={
        "email": email, "password": PASSWORD, "full_name": f"Test {role.title()}",
    })
    if r.status_code != 201:
        sys.exit(f"[FAIL] register {role}: {r.status_code} — {r.text[:200]}")
    user_id = r.json()["id"]
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET email_verified = TRUE, role = %s WHERE id = %s", (role, user_id))
        conn.commit()
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    if r.status_code != 200:
        sys.exit(f"[FAIL] login {role}: {r.status_code} — {r.text[:200]}")
    return r.json()["access_token"], user_id


# ── Test Steps ────────────────────────────────────────────────────────────────

def step_role_access_control(citizen_token: str, clerk_token: str, admin_token: str):
    print("\n--- Step 1: Role-based access control ---")

    # Citizen cannot access admin endpoints
    r = requests.get(f"{API}/admin/cases", headers=auth_headers(citizen_token))
    assert_status("citizen -> admin/cases", r, 403)

    r = requests.get(f"{API}/admin/audit-logs", headers=auth_headers(citizen_token))
    assert_status("citizen -> admin/audit-logs", r, 403)

    r = requests.get(f"{API}/admin/stats", headers=auth_headers(citizen_token))
    assert_status("citizen -> admin/stats", r, 403)

    # Clerk can access admin endpoints
    r = requests.get(f"{API}/admin/cases", headers=auth_headers(clerk_token))
    assert_status("clerk -> admin/cases", r, 200)

    # Admin can access admin endpoints
    r = requests.get(f"{API}/admin/stats", headers=auth_headers(admin_token))
    assert_status("admin -> admin/stats", r, 200)


def step_create_citizen_case(citizen_token: str) -> str:
    print("\n--- Step 2: Create citizen case ---")
    r = requests.post(f"{API}/cases", json={
        "service_type": "id_new",
        "declared_fields": {"full_name": "Test Citizen"},
    }, headers=auth_headers(citizen_token))
    assert_status("citizen creates case", r, 201)
    case_id = r.json()["id"]

    # Force to risk_evaluated (simulating pipeline completion)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE cases SET status = 'risk_evaluated' WHERE id = %s", (case_id,)
        )
        conn.commit()
    return case_id


def step_clerk_list_cases(clerk_token: str, case_id: str):
    print("\n--- Step 3: Clerk lists all cases ---")
    r = requests.get(f"{API}/admin/cases", headers=auth_headers(clerk_token))
    assert_status("GET /admin/cases", r, 200)
    body = r.json()
    assert_eq("has cases", isinstance(body["cases"], list), True)

    # Filter by status
    r = requests.get(f"{API}/admin/cases?status=risk_evaluated", headers=auth_headers(clerk_token))
    assert_status("GET /admin/cases?status=risk_evaluated", r, 200)
    case_ids = [c["id"] for c in r.json()["cases"]]
    assert_eq("our case in results", case_id in case_ids, True)


def step_clerk_approve_case(clerk_token: str, case_id: str):
    print("\n--- Step 4: Clerk approves case ---")
    r = requests.patch(f"{API}/cases/{case_id}/status", json={
        "status": "approved",
        "notes": "All documents verified, approved by clerk.",
    }, headers=auth_headers(clerk_token))
    assert_status("PATCH /status -> approved", r, 200)
    # Should auto-chain to payment_pending
    assert_eq("auto-chained to payment_pending", r.json()["status"], "payment_pending")


def step_clerk_reject_case(clerk_token: str, citizen_token: str) -> str:
    print("\n--- Step 5: Clerk rejects a case ---")
    # Create another case
    r = requests.post(f"{API}/cases", json={
        "service_type": "passport_new", "declared_fields": {},
    }, headers=auth_headers(citizen_token))
    case_id = r.json()["id"]

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE cases SET status = 'risk_evaluated' WHERE id = %s", (case_id,))
        conn.commit()

    r = requests.patch(f"{API}/cases/{case_id}/status", json={
        "status": "rejected",
        "notes": "Documents are blurry and unreadable.",
        "rejection_reasons": ["Blurry national ID", "Civil registry extract expired"],
    }, headers=auth_headers(clerk_token))
    assert_status("PATCH /status -> rejected", r, 200)
    assert_eq("status is rejected", r.json()["status"], "rejected")
    assert_eq("has rejection reasons", len(r.json()["rejection_reasons"]), 2)
    return case_id


def step_clerk_need_info(clerk_token: str, citizen_token: str) -> str:
    print("\n--- Step 6: Clerk requests more info ---")
    r = requests.post(f"{API}/cases", json={
        "service_type": "id_renewal", "declared_fields": {},
    }, headers=auth_headers(citizen_token))
    case_id = r.json()["id"]

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE cases SET status = 'risk_evaluated' WHERE id = %s", (case_id,))
        conn.commit()

    r = requests.patch(f"{API}/cases/{case_id}/status", json={
        "status": "need_info",
        "notes": "Please upload a clearer photo of your old ID.",
    }, headers=auth_headers(clerk_token))
    assert_status("PATCH /status -> need_info", r, 200)
    assert_eq("status is need_info", r.json()["status"], "need_info")
    return case_id


def step_invalid_transitions(clerk_token: str, case_id: str):
    print("\n--- Step 7: Invalid state transitions ---")
    # rejected -> approved should fail
    r = requests.patch(f"{API}/cases/{case_id}/status", json={
        "status": "approved",
    }, headers=auth_headers(clerk_token))
    assert_status("rejected -> approved fails", r, 400)

    # rejected -> in_production should fail
    r = requests.patch(f"{API}/cases/{case_id}/status", json={
        "status": "in_production",
    }, headers=auth_headers(clerk_token))
    assert_status("rejected -> in_production fails", r, 400)


def step_citizen_cannot_update_status(citizen_token: str, case_id: str):
    print("\n--- Step 8: Citizen cannot update case status ---")
    r = requests.patch(f"{API}/cases/{case_id}/status", json={
        "status": "approved",
    }, headers=auth_headers(citizen_token))
    assert_status("citizen PATCH /status rejected", r, 403)


def step_audit_logs(admin_token: str):
    print("\n--- Step 9: Audit logs ---")
    r = requests.get(f"{API}/admin/audit-logs", headers=auth_headers(admin_token))
    assert_status("GET /admin/audit-logs", r, 200)
    body = r.json()
    assert_eq("has logs", isinstance(body["logs"], list), True)
    assert_eq("has at least 1 log", len(body["logs"]) > 0, True)

    # Each log should have required fields
    log = body["logs"][0]
    assert_eq("log has action", "action" in log, True)
    assert_eq("log has created_at", "created_at" in log, True)


def step_admin_stats(admin_token: str):
    print("\n--- Step 10: Dashboard stats ---")
    r = requests.get(f"{API}/admin/stats", headers=auth_headers(admin_token))
    assert_status("GET /admin/stats", r, 200)
    body = r.json()
    assert_eq("has total_cases", "total_cases" in body, True)
    assert_eq("total_cases >= 0", body["total_cases"] >= 0, True)


# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup(*user_ids):
    with db_conn() as conn, conn.cursor() as cur:
        for uid in user_ids:
            # Delete audit_logs referencing cases first (FK constraint)
            cur.execute("DELETE FROM audit_logs WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (uid,))
            cur.execute("DELETE FROM audit_logs WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM payments WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (uid,))
            cur.execute("DELETE FROM documents WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (uid,))
            cur.execute("DELETE FROM face_results WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (uid,))
            cur.execute("DELETE FROM cases WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM email_verification_tokens WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.commit()
    print(f"\n[CLEANUP] Removed {len(user_ids)} test users and related data")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Admin/Clerk Flow E2E Integration Test")
    print(f"  Target: {BASE_URL}")
    print("=" * 60)

    wait_for_gateway()
    flush_rate_limits()

    citizen_token, citizen_id = create_user(CITIZEN_EMAIL, "citizen")
    clerk_token, clerk_id = create_user(CLERK_EMAIL, "clerk")
    admin_token, admin_id = create_user(ADMIN_EMAIL, "admin")

    try:
        step_role_access_control(citizen_token, clerk_token, admin_token)
        case_id = step_create_citizen_case(citizen_token)
        step_clerk_list_cases(clerk_token, case_id)
        step_clerk_approve_case(clerk_token, case_id)
        rejected_id = step_clerk_reject_case(clerk_token, citizen_token)
        step_clerk_need_info(clerk_token, citizen_token)
        step_invalid_transitions(clerk_token, rejected_id)
        step_citizen_cannot_update_status(citizen_token, case_id)
        step_audit_logs(admin_token)
        step_admin_stats(admin_token)

        print("\n" + "=" * 60)
        print("  ALL ADMIN/CLERK TESTS PASSED")
        print("=" * 60)
    finally:
        cleanup(citizen_id, clerk_id, admin_id)
        flush_rate_limits()


if __name__ == "__main__":
    main()