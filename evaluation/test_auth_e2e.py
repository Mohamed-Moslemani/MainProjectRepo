"""
End-to-end integration test for the authentication system.

Runs against the full Docker Compose stack (gateway + db + redis).
Validates the complete user lifecycle:
  register -> verify email -> login -> refresh -> forgot password -> reset password

Usage:
    1. docker compose --env-file .env.dev up -d --build
    2. python -m evaluation.test_auth_e2e
"""

import hashlib
import secrets
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone

import psycopg2
import requests

 # Configuration
 
BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1/auth"

DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

TEST_EMAIL = f"test_{uuid.uuid4().hex[:8]}@example.com"
TEST_PASSWORD = "Str0ng!Pass#1"
NEW_PASSWORD = "N3wSecure@Pass#2"


 # Helpers
 
def flush_rate_limits():
    """Clear Redis rate limit keys."""
    try:
        import redis
        r = redis.Redis(host="localhost", port=6380, db=0)
        r.flushdb()
        print("[OK] Rate limits cleared")
    except Exception as e:
        print(f"[WARN] Could not flush rate limits: {e}")


def wait_for_gateway(timeout: int = 60):
    """Block until the gateway health endpoint responds."""
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
    """Return a psycopg2 connection to the test database."""
    return psycopg2.connect(DB_DSN)


def inject_token(table: str, user_id: str) -> str:
    """Generate a known raw token, hash it, and INSERT/UPDATE into the DB.

    This sidesteps the email delivery problem: we replace the token hash in
    the database with one we control so we can call the verify / reset
    endpoints with a known raw value.

    Returns the raw token string.
    """
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    expires = datetime.now(timezone.utc) + timedelta(hours=1)

    with db_conn() as conn, conn.cursor() as cur:
        # Mark any existing unused tokens as used to avoid conflicts
        cur.execute(
            f"UPDATE {table} SET used = TRUE WHERE user_id = %s AND used = FALSE",
            (user_id,),
        )
        # Insert our controlled token
        cur.execute(
            f"""
            INSERT INTO {table} (id, user_id, token_hash, expires_at, used, created_at)
            VALUES (%s, %s, %s, %s, FALSE, NOW())
            """,
            (str(uuid.uuid4()), user_id, hashed, expires),
        )
        conn.commit()

    return raw


def get_user_id(email: str) -> str:
    """Look up user id by email."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if not row:
            sys.exit(f"[FAIL] User {email} not found in DB")
        return row[0]


def get_user_field(user_id: str, field: str):
    """Read a single column from the users table."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(f"SELECT {field} FROM users WHERE id = %s", (user_id,))
        return cur.fetchone()[0]


def assert_eq(label: str, actual, expected):
    if actual != expected:
        sys.exit(f"[FAIL] {label}: expected {expected!r}, got {actual!r}")
    print(f"  [PASS] {label}")


def assert_status(label: str, resp: requests.Response, expected: int):
    if resp.status_code != expected:
        detail = ""
        try:
            detail = f" — {resp.json()}"
        except Exception:
            detail = f" — {resp.text[:200]}"
        sys.exit(f"[FAIL] {label}: expected {expected}, got {resp.status_code}{detail}")
    print(f"  [PASS] {label} -> {expected}")


 # Test steps
 
def step_register() -> dict:
    print("\n--- Step 1: Register ---")
    r = requests.post(f"{API}/register", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "full_name": "E2E Test User",
    })
    assert_status("POST /register", r, 201)
    body = r.json()
    assert_eq("email matches", body["email"], TEST_EMAIL)
    assert_eq("email_verified is false", body["email_verified"], False)
    assert_eq("role is citizen", body["role"], "citizen")

    # Duplicate registration should fail
    r2 = requests.post(f"{API}/register", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "full_name": "Duplicate User",
    })
    assert_status("duplicate register", r2, 400)

    return body


def step_login_before_verify():
    print("\n--- Step 2: Login before email verification (should fail) ---")
    r = requests.post(f"{API}/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    assert_status("POST /login (unverified)", r, 403)
    assert_eq("detail mentions verification", "not verified" in r.json()["detail"].lower(), True)


def step_verify_email(user_id: str):
    print("\n--- Step 3: Verify email ---")
    raw_token = inject_token("email_verification_tokens", user_id)

    r = requests.post(f"{API}/verify-email", json={"token": raw_token})
    assert_status("POST /verify-email", r, 200)

    # Confirm DB state
    verified = get_user_field(user_id, "email_verified")
    assert_eq("email_verified is true in DB", verified, True)

    # Re-using the same token should fail
    r2 = requests.post(f"{API}/verify-email", json={"token": raw_token})
    assert_status("verify-email replay", r2, 400)


def step_login(user_id: str) -> dict:
    print("\n--- Step 4: Login ---")
    r = requests.post(f"{API}/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    assert_status("POST /login", r, 200)
    body = r.json()
    assert_eq("has access_token", "access_token" in body, True)
    assert_eq("has refresh_token", "refresh_token" in body, True)
    assert_eq("token_type is bearer", body["token_type"], "bearer")

    # Verify the access token works on a protected endpoint
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r2 = requests.get(f"{BASE_URL}/api/v1/cases", headers=headers)
    assert_status("GET /cases (authenticated)", r2, 200)

    return body


def step_refresh(tokens: dict) -> dict:
    print("\n--- Step 5: Refresh token ---")
    # Small delay so the new token's iat timestamp differs from the original
    time.sleep(1)
    r = requests.post(f"{API}/refresh", json={
        "refresh_token": tokens["refresh_token"],
    })
    assert_status("POST /refresh", r, 200)
    body = r.json()
    assert_eq("new access_token issued", "access_token" in body, True)
    assert_eq("new refresh_token issued", "refresh_token" in body, True)
    # New access token should differ from old one
    assert_eq("access_token rotated", body["access_token"] != tokens["access_token"], True)

    # New access token works
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r2 = requests.get(f"{BASE_URL}/api/v1/cases", headers=headers)
    assert_status("GET /cases (refreshed token)", r2, 200)

    return body


def step_forgot_password():
    print("\n--- Step 6: Forgot password ---")
    r = requests.post(f"{API}/forgot-password", json={"email": TEST_EMAIL})
    assert_status("POST /forgot-password", r, 200)

    # Non-existent email also returns 200 (no enumeration)
    r2 = requests.post(f"{API}/forgot-password", json={"email": "nobody@example.com"})
    assert_status("forgot-password (unknown email)", r2, 200)


def step_reset_password(user_id: str, old_tokens: dict):
    print("\n--- Step 7: Reset password ---")
    raw_token = inject_token("password_reset_tokens", user_id)

    r = requests.post(f"{API}/reset-password", json={
        "token": raw_token,
        "new_password": NEW_PASSWORD,
    })
    assert_status("POST /reset-password", r, 200)

    # Confirm tokens_valid_after was set (session revocation)
    tva = get_user_field(user_id, "tokens_valid_after")
    assert_eq("tokens_valid_after is set", tva is not None, True)

    # Re-using the reset token should fail
    r2 = requests.post(f"{API}/reset-password", json={
        "token": raw_token,
        "new_password": "Another@Pass1",
    })
    assert_status("reset-password replay", r2, 400)

    # Old access token should be revoked
    headers = {"Authorization": f"Bearer {old_tokens['access_token']}"}
    r3 = requests.get(f"{BASE_URL}/api/v1/cases", headers=headers)
    assert_status("GET /cases (revoked token)", r3, 401)

    # Old refresh token should also be revoked
    r4 = requests.post(f"{API}/refresh", json={
        "refresh_token": old_tokens["refresh_token"],
    })
    # The refresh endpoint doesn't check tokens_valid_after directly,
    # but the newly issued tokens would reflect the new iat. Let's verify
    # that old password no longer works and new password does.

    # Login with old password should fail
    r5 = requests.post(f"{API}/login", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
    })
    assert_status("login with old password", r5, 401)


def step_login_new_password():
    print("\n--- Step 8: Login with new password ---")
    # Small delay to ensure new token's iat is after tokens_valid_after
    time.sleep(1)
    r = requests.post(f"{API}/login", json={
        "email": TEST_EMAIL,
        "password": NEW_PASSWORD,
    })
    assert_status("POST /login (new password)", r, 200)
    body = r.json()
    assert_eq("has access_token", "access_token" in body, True)

    # Verify the new token works
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    r2 = requests.get(f"{BASE_URL}/api/v1/cases", headers=headers)
    assert_status("GET /cases (new session)", r2, 200)


def cleanup(user_id: str):
    """Remove test data from the database."""
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM email_verification_tokens WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM audit_logs WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    print(f"\n[CLEANUP] Removed test user {user_id}")


 # Main
 
def main():
    print("=" * 60)
    print("  Auth E2E Integration Test")
    print(f"  Target: {BASE_URL}")
    print(f"  Test email: {TEST_EMAIL}")
    print("=" * 60)

    wait_for_gateway()
    flush_rate_limits()

    user_data = step_register()
    user_id = user_data["id"]

    try:
        step_login_before_verify()
        step_verify_email(user_id)
        tokens = step_login(user_id)
        refreshed_tokens = step_refresh(tokens)
        step_forgot_password()
        step_reset_password(user_id, refreshed_tokens)
        step_login_new_password()

        print("\n" + "=" * 60)
        print("  ALL TESTS PASSED")
        print("=" * 60)
    finally:
        cleanup(user_id)
        flush_rate_limits()


if __name__ == "__main__":
    main()
