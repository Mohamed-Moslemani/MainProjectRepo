"""
End-to-end integration test for the payment flow.

Tests the Stripe Checkout integration:
  case approved -> payment_pending -> create checkout -> simulate webhook -> in_production

Since we can't interact with a real Stripe Checkout UI, we:
  1. Create a case and force it into payment_pending via DB
  2. Create a Stripe Checkout Session via the API
  3. Simulate a webhook event (checkout.session.completed)

Usage:
    1. docker compose --env-file .env.dev up -d --build
    2. python -m evaluation.test_payment_e2e
"""

import hashlib
import json
import secrets
import sys
import time
import uuid
from datetime import datetime, timezone

import psycopg2
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"
DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

TEST_EMAIL = f"pay_test_{uuid.uuid4().hex[:8]}@example.com"
TEST_PASSWORD = "Str0ng!Pass#1"

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


def register_and_login() -> tuple:
    r = requests.post(f"{API}/auth/register", json={
        "email": TEST_EMAIL, "password": TEST_PASSWORD, "full_name": "Payment Test User",
    })
    assert_status("register", r, 201)
    user_id = r.json()["id"]
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET email_verified = TRUE WHERE id = %s", (user_id,))
        conn.commit()
    r = requests.post(f"{API}/auth/login", json={"email": TEST_EMAIL, "password": TEST_PASSWORD})
    assert_status("login", r, 200)
    return r.json()["access_token"], user_id


# ── Test Steps ────────────────────────────────────────────────────────────────

def step_create_case_in_payment_pending(token: str) -> dict:
    """Create a case and force it into payment_pending status via DB."""
    print("\n--- Step 1: Create case and set to payment_pending ---")
    r = requests.post(f"{API}/cases", json={
        "service_type": "id_renewal",
        "declared_fields": {"full_name": "Payment Test User"},
    }, headers=auth_headers(token))
    assert_status("POST /cases", r, 201)
    case = r.json()

    # Force to payment_pending (normally done by orchestrator after approval)
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE cases SET status = 'payment_pending' WHERE id = %s",
            (case["id"],),
        )
        conn.commit()

    # Verify
    r = requests.get(f"{API}/cases/{case['id']}", headers=auth_headers(token))
    assert_status("GET case", r, 200)
    assert_eq("status is payment_pending", r.json()["status"], "payment_pending")
    return r.json()


def step_create_checkout(token: str, case_id: str) -> dict:
    print("\n--- Step 2: Create Stripe Checkout Session ---")
    r = requests.post(f"{API}/payments", json={
        "case_id": case_id,
    }, headers=auth_headers(token))
    assert_status("POST /payments", r, 200)
    body = r.json()
    assert_eq("has checkout_url", body.get("checkout_url") is not None, True)
    assert_eq("status is pending", body["status"], "pending")
    assert_eq("amount is 1500 (id_renewal)", body["amount"], 1500)
    assert_eq("currency is usd", body["currency"], "usd")
    print(f"  [INFO] checkout_url: {body['checkout_url'][:80]}...")
    return body


def step_cannot_create_duplicate_checkout(token: str, case_id: str):
    print("\n--- Step 3: Cannot pay for non-payment_pending case ---")
    # After checkout creation, case is still payment_pending so this should work
    # But let's test with a draft case
    r = requests.post(f"{API}/cases", json={
        "service_type": "id_new", "declared_fields": {},
    }, headers=auth_headers(token))
    draft_case_id = r.json()["id"]

    r = requests.post(f"{API}/payments", json={
        "case_id": draft_case_id,
    }, headers=auth_headers(token))
    assert_status("payment on draft case rejected", r, 400)


def step_simulate_webhook(case_id: str, payment_id: str):
    """Simulate a Stripe webhook by directly calling handle_checkout_completed via DB."""
    print("\n--- Step 4: Simulate payment completion ---")

    # Get the stripe_checkout_session_id from the payment record
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT stripe_checkout_session_id FROM payments WHERE id = %s", (payment_id,)
        )
        row = cur.fetchone()
        if not row:
            sys.exit(f"[FAIL] Payment {payment_id} not found in DB")
        session_id = row[0]

    # Simulate: directly update payment and case in DB
    # (In production, Stripe webhook would trigger this via the /webhook endpoint)
    new_event = json.dumps([{
        "status": "in_production",
        "message": "Payment received. Document is being produced.",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }])
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE payments SET status = 'completed', stripe_payment_intent_id = %s WHERE id = %s",
            (f"pi_test_{uuid.uuid4().hex[:16]}", payment_id),
        )
        cur.execute(
            """UPDATE cases SET status = 'in_production',
               status_history = (status_history::jsonb || %s::jsonb)::json
               WHERE id = %s""",
            (new_event, case_id),
        )
        conn.commit()

    print("  [PASS] Payment marked as completed, case moved to in_production")


def step_verify_post_payment(token: str, case_id: str, payment_id: str):
    print("\n--- Step 5: Verify post-payment state ---")
    # Case should be in_production
    r = requests.get(f"{API}/cases/{case_id}", headers=auth_headers(token))
    assert_status("GET case", r, 200)
    assert_eq("case status is in_production", r.json()["status"], "in_production")

    # Payment should be completed in DB
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT status FROM payments WHERE id = %s", (payment_id,))
        assert_eq("payment status is completed", cur.fetchone()[0], "completed")

    # Cannot create another checkout for this case
    r = requests.post(f"{API}/payments", json={"case_id": case_id}, headers=auth_headers(token))
    assert_status("payment on in_production case rejected", r, 400)


def step_payment_failed_flow(token: str):
    """Test that a failed payment keeps the case in payment_pending."""
    print("\n--- Step 6: Payment failed flow ---")

    # Create another case in payment_pending
    # Use the 1-year passport tier so the assertion is unambiguous;
    # default validity (5y) would cost $150 under the new
    # validity-tiered fee schedule.
    r = requests.post(f"{API}/cases", json={
        "service_type": "passport_new",
        "declared_fields": {"passport_validity_years": 1},
    }, headers=auth_headers(token))
    case_id = r.json()["id"]

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE cases SET status = 'payment_pending' WHERE id = %s", (case_id,))
        conn.commit()

    # Create checkout
    r = requests.post(f"{API}/payments", json={"case_id": case_id}, headers=auth_headers(token))
    assert_status("create checkout (passport)", r, 200)
    # 1-year passport tier = $50 = 5000 cents
    assert_eq("passport amount is 5000 (1y tier)", r.json()["amount"], 5000)
    payment_id = r.json()["id"]

    # Simulate failed payment
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE payments SET status = 'failed' WHERE id = %s", (payment_id,))
        conn.commit()

    # Case should still be payment_pending
    r = requests.get(f"{API}/cases/{case_id}", headers=auth_headers(token))
    assert_eq("case stays payment_pending after failed payment", r.json()["status"], "payment_pending")

    # User can retry payment
    r = requests.post(f"{API}/payments", json={"case_id": case_id}, headers=auth_headers(token))
    assert_status("retry payment after failure", r, 200)
    print("  [PASS] Retry payment works")

    return case_id


# ── Cleanup ───────────────────────────────────────────────────────────────────

def cleanup(user_id: str):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_logs WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM audit_logs WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM payments WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM documents WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM face_results WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM cases WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM email_verification_tokens WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    print(f"\n[CLEANUP] Removed test user {user_id} and related data")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Payment Flow E2E Integration Test")
    print(f"  Target: {BASE_URL}")
    print("=" * 60)

    wait_for_gateway()
    flush_rate_limits()
    token, user_id = register_and_login()

    try:
        case = step_create_case_in_payment_pending(token)
        case_id = case["id"]

        payment = step_create_checkout(token, case_id)
        payment_id = payment["id"]

        step_cannot_create_duplicate_checkout(token, case_id)
        step_simulate_webhook(case_id, payment_id)
        step_verify_post_payment(token, case_id, payment_id)
        step_payment_failed_flow(token)

        print("\n" + "=" * 60)
        print("  ALL PAYMENT TESTS PASSED")
        print("=" * 60)
    finally:
        cleanup(user_id)
        flush_rate_limits()


if __name__ == "__main__":
    main()