"""End-to-end integration test for the passport_new service type.

First-time passport applicant. Different from passport_renewal in
three ways:
  - no old passport → no MRZ check, no pre-2016 eligibility rule
  - face match uses the photo on the civil-registry extract as the
    reference (passport_renewal uses old_passport_data_page)
  - after payment the case routes to BIOMETRIC_APPOINTMENT_REQUIRED
    (the citizen has no fingerprints on file yet)

Same as passport_renewal: needs a mukhtar attestation before approval.

Expected flow:
    register → seed mukhtar → login → create passport_new case →
    upload national_id_front + back + civil_registry_extract → liveness →
    submit → pipeline (3 OCR + face vs registry photo + reconcile + risk) →
    pending_mukhtar (auto-assigned to seeded mukhtar in same area) →
    assert OCRResult × 3, FaceResult × 1, mukhtar_id set.

Runs against Docker Compose with OCR_MOCK_MODE + FACE_MOCK_MODE on.
"""

import sys
import time
import uuid

import psycopg2
import requests

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"
DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

TEST_EMAIL = f"passport_new_test_{uuid.uuid4().hex[:8]}@example.com"
MUKHTAR_EMAIL = f"mukhtar_pn_{uuid.uuid4().hex[:8]}@example.com"
TEST_PASSWORD = "Str0ng!Pass#1"
SERVICE_TYPE = "passport_new"
REGISTRY_PLACE = "Beirut"
MUNICIPALITY = "Beirut Central"

DECLARED_FIELDS = {
    "full_name": "Mohamed Saad",
    "father_name": "Ali Saad",
    "mother_name": "Fatima Hassan",
    "date_of_birth": "15/06/1995",
    "place_of_birth": "Beirut",
    "registry_number": "12345",
    "registry_place": REGISTRY_PLACE,
    "passport_validity_years": 5,
}


# ── Helpers ───────────────────────────────────────────────────────────────

def flush_rate_limits():
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


def assert_truthy(label, value):
    if not value:
        sys.exit(f"[FAIL] {label}: value was falsy ({value!r})")
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


def create_test_image() -> bytes:
    return bytes([
        0xFF, 0xD8, 0xFF, 0xE0, 0x00, 0x10, 0x4A, 0x46, 0x49, 0x46, 0x00, 0x01,
        0x01, 0x00, 0x00, 0x01, 0x00, 0x01, 0x00, 0x00, 0xFF, 0xDB, 0x00, 0x43,
        0x00, 0x08, 0x06, 0x06, 0x07, 0x06, 0x05, 0x08, 0x07, 0x07, 0x07, 0x09,
        0x09, 0x08, 0x0A, 0x0C, 0x14, 0x0D, 0x0C, 0x0B, 0x0B, 0x0C, 0x19, 0x12,
        0x13, 0x0F, 0x14, 0x1D, 0x1A, 0x1F, 0x1E, 0x1D, 0x1A, 0x1C, 0x1C, 0x20,
        0x24, 0x2E, 0x27, 0x20, 0x22, 0x2C, 0x23, 0x1C, 0x1C, 0x28, 0x37, 0x29,
        0x2C, 0x30, 0x31, 0x34, 0x34, 0x34, 0x1F, 0x27, 0x39, 0x3D, 0x38, 0x32,
        0x3C, 0x2E, 0x33, 0x34, 0x32, 0xFF, 0xC0, 0x00, 0x0B, 0x08, 0x00, 0x01,
        0x00, 0x01, 0x01, 0x01, 0x11, 0x00, 0xFF, 0xC4, 0x00, 0x1F, 0x00, 0x00,
        0x01, 0x05, 0x01, 0x01, 0x01, 0x01, 0x01, 0x01, 0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00, 0x01, 0x02, 0x03, 0x04, 0x05, 0x06, 0x07, 0x08,
        0x09, 0x0A, 0x0B, 0xFF, 0xC4, 0x00, 0xB5, 0x10, 0x00, 0x02, 0x01, 0x03,
        0x03, 0x02, 0x04, 0x03, 0x05, 0x05, 0x04, 0x04, 0x00, 0x00, 0x01, 0x7D,
        0x01, 0x02, 0x03, 0x00, 0x04, 0x11, 0x05, 0x12, 0x21, 0x31, 0x41, 0x06,
        0x13, 0x51, 0x61, 0x07, 0x22, 0x71, 0x14, 0x32, 0x81, 0x91, 0xA1, 0x08,
        0x23, 0x42, 0xB1, 0xC1, 0x15, 0x52, 0xD1, 0xF0, 0x24, 0x33, 0x62, 0x72,
        0x82, 0x09, 0x0A, 0x16, 0x17, 0x18, 0x19, 0x1A, 0x25, 0x26, 0x27, 0x28,
        0x29, 0x2A, 0x34, 0x35, 0x36, 0x37, 0x38, 0x39, 0x3A, 0x43, 0x44, 0x45,
        0x46, 0x47, 0x48, 0x49, 0x4A, 0x53, 0x54, 0x55, 0x56, 0x57, 0x58, 0x59,
        0x5A, 0x63, 0x64, 0x65, 0x66, 0x67, 0x68, 0x69, 0x6A, 0x73, 0x74, 0x75,
        0x76, 0x77, 0x78, 0x79, 0x7A, 0x83, 0x84, 0x85, 0x86, 0x87, 0x88, 0x89,
        0x8A, 0x92, 0x93, 0x94, 0x95, 0x96, 0x97, 0x98, 0x99, 0x9A, 0xA2, 0xA3,
        0xA4, 0xA5, 0xA6, 0xA7, 0xA8, 0xA9, 0xAA, 0xB2, 0xB3, 0xB4, 0xB5, 0xB6,
        0xB7, 0xB8, 0xB9, 0xBA, 0xC2, 0xC3, 0xC4, 0xC5, 0xC6, 0xC7, 0xC8, 0xC9,
        0xCA, 0xD2, 0xD3, 0xD4, 0xD5, 0xD6, 0xD7, 0xD8, 0xD9, 0xDA, 0xE1, 0xE2,
        0xFF, 0xDA, 0x00, 0x08, 0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0x7B, 0x94,
        0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xFF, 0xD9,
    ])


def register_and_login() -> tuple[str, str]:
    r = requests.post(f"{API}/auth/register", json={
        "email": TEST_EMAIL, "password": TEST_PASSWORD,
        "full_name": "Mohamed Saad",
        "father_name": "Ali Saad", "mother_name": "Fatima Hassan",
        "date_of_birth": "1995-06-15", "place_of_birth": "Beirut",
        "gender": "male", "registry_number": "12345",
        "registry_place": REGISTRY_PLACE,
    })
    assert_status("register citizen", r, 201)
    user_id = r.json()["id"]

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET email_verified = TRUE WHERE id = %s", (user_id,))
        conn.commit()

    r = requests.post(f"{API}/auth/login", json={
        "email": TEST_EMAIL, "password": TEST_PASSWORD,
    })
    assert_status("login citizen", r, 200)
    return r.json()["access_token"], user_id


def seed_mukhtar() -> str:
    """Insert a mukhtar in the citizen's registry area so auto-assign picks them."""
    from passlib.hash import bcrypt
    mukhtar_id = str(uuid.uuid4())
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (
                id, email, password_hash, full_name, role, email_verified,
                registry_place, municipality, registry_number, created_at
            ) VALUES (%s, %s, %s, %s, 'mukhtar', TRUE, %s, %s, '99999', NOW())
            """,
            (mukhtar_id, MUKHTAR_EMAIL, bcrypt.hash(TEST_PASSWORD),
             "Mukhtar Beirut", REGISTRY_PLACE, MUNICIPALITY),
        )
        conn.commit()
    print(f"  [SEED] mukhtar id={mukhtar_id[:8]}… at {MUNICIPALITY}/{REGISTRY_PLACE}")
    return mukhtar_id


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Steps ─────────────────────────────────────────────────────────────────

def step_create_case(token: str) -> dict:
    print("\n--- Step 1: Create passport_new case ---")
    r = requests.post(
        f"{API}/cases",
        json={"service_type": SERVICE_TYPE, "declared_fields": {}},
        headers=auth_headers(token),
    )
    assert_status("POST /cases", r, 201)
    body = r.json()
    assert_eq("status is draft", body["status"], "draft")
    assert_eq("service_type matches", body["service_type"], SERVICE_TYPE)
    return body


def step_required_docs(token: str, case_id: str):
    print("\n--- Step 2: Required docs include national_id + civil registry ---")
    r = requests.get(f"{API}/cases/{case_id}/required-documents", headers=auth_headers(token))
    assert_status("GET /required-documents", r, 200)
    docs = r.json()["required_documents"]
    assert_truthy("national_id_front required", "national_id_front" in docs)
    assert_truthy("national_id_back required", "national_id_back" in docs)
    assert_truthy("civil_registry_extract required", "civil_registry_extract" in docs)
    assert_truthy("liveness_capture required", "liveness_capture" in docs)
    # First-time applicant has no prior passport — must NOT request one.
    assert_truthy("old_passport_data_page NOT required", "old_passport_data_page" not in docs)


def step_upload_three_docs(token: str, case_id: str):
    print("\n--- Step 3: Upload 3 OCR documents ---")
    img = create_test_image()
    for doc_type in ("national_id_front", "national_id_back", "civil_registry_extract"):
        r = requests.post(
            f"{API}/cases/{case_id}/documents",
            files={"file": (f"{doc_type}.jpg", img, "image/jpeg")},
            data={"document_type": doc_type},
            headers=auth_headers(token),
        )
        assert_status(f"upload {doc_type}", r, 200)


def step_liveness_flow(token: str, case_id: str):
    print("\n--- Step 4: Liveness session ---")
    r = requests.post(
        f"{API}/liveness/create-session",
        json={"case_id": case_id},
        headers=auth_headers(token),
    )
    assert_status("POST /liveness/create-session", r, 200)
    session_id = r.json()["session_id"]

    r = requests.post(
        f"{API}/liveness/get-results",
        json={"case_id": case_id, "session_id": session_id},
        headers=auth_headers(token),
    )
    assert_status("POST /liveness/get-results", r, 200)
    assert_eq("liveness status SUCCEEDED", r.json()["status"], "SUCCEEDED")


def step_submit(token: str, case_id: str):
    print("\n--- Step 5: Submit case ---")
    r = requests.post(
        f"{API}/cases/{case_id}/submit",
        json={"declared_fields": DECLARED_FIELDS},
        headers=auth_headers(token),
    )
    assert_status("POST /submit", r, 200)


def step_wait_for_pipeline(token: str, case_id: str, timeout: int = 60) -> dict:
    print(f"\n--- Step 6: Wait for pipeline (max {timeout}s) ---")
    deadline = time.time() + timeout
    transient = {"submitted", "validated", "risk_evaluated"}
    last_status = None
    while time.time() < deadline:
        r = requests.get(f"{API}/cases/{case_id}", headers=auth_headers(token))
        if r.status_code != 200:
            time.sleep(1)
            continue
        body = r.json()
        status = body["status"]
        if status != last_status:
            print(f"  [status] {status}")
            last_status = status
        if status not in transient and status != "draft":
            return body
        time.sleep(1)
    sys.exit(f"[FAIL] Pipeline did not finish — last status: {last_status}")


def step_assert_pending_mukhtar(case_body: dict, mukhtar_id: str, user_id: str):
    print("\n--- Step 7: Pipeline routed to pending_mukhtar + auto-assigned ---")

    assert_eq("final status", case_body["status"], "pending_mukhtar")
    assert_eq("mukhtar auto-assigned to seeded mukhtar",
              case_body.get("mukhtar_id"), mukhtar_id)

    assert_truthy("liveness_result populated", case_body.get("liveness_result"))
    assert_truthy("reconciliation_result populated", case_body.get("reconciliation_result"))
    assert_truthy("risk_result populated", case_body.get("risk_result"))

    # 3 OCR docs → 3 OCRResult rows; 1 face check → 1 FaceResult row
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(*) FROM ocr_results
            WHERE document_id IN (
                SELECT d.id FROM documents d
                JOIN cases c ON d.case_id = c.id
                WHERE c.user_id = %s
            )
            """,
            (user_id,),
        )
        ocr_count = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COUNT(*) FROM face_results
            WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)
            """,
            (user_id,),
        )
        face_count = cur.fetchone()[0]

    assert_eq("3 OCR results stored", ocr_count, 3)
    assert_eq("1 face result stored", face_count, 1)


def step_no_mrz_for_passport_new(case_id: str):
    """passport_new has no old passport, so the orchestrator must NOT
    have logged an MRZ result. Guards against accidental wiring of the
    passport_renewal MRZ branch into passport_new."""
    print("\n--- Step 8: No MRZ artifact (no old passport uploaded) ---")
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT details FROM audit_logs
             WHERE case_id = %s AND action = 'ocr_completed'
            """,
            (case_id,),
        )
        rows = [r[0] for r in cur.fetchall()]
    mrz_found = any((r or {}).get("mrz") for r in rows)
    assert_truthy("no MRZ in any ocr_completed log", not mrz_found)


# ── Cleanup ───────────────────────────────────────────────────────────────

def cleanup(user_id: str, mukhtar_id: str):
    with db_conn() as conn, conn.cursor() as cur:
        # Wipe both the citizen's data + the seeded mukhtar
        for uid in (user_id, mukhtar_id):
            cur.execute(
                "DELETE FROM audit_logs WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)",
                (uid,),
            )
            cur.execute("DELETE FROM audit_logs WHERE user_id = %s", (uid,))
            cur.execute(
                "DELETE FROM face_results WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)",
                (uid,),
            )
            cur.execute(
                "DELETE FROM ocr_results WHERE document_id IN (SELECT d.id FROM documents d JOIN cases c ON d.case_id = c.id WHERE c.user_id = %s)",
                (uid,),
            )
            cur.execute(
                "DELETE FROM documents WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)",
                (uid,),
            )
            cur.execute(
                "DELETE FROM payments WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)",
                (uid,),
            )
            cur.execute("DELETE FROM cases WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM email_verification_tokens WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (uid,))
            cur.execute("DELETE FROM users WHERE id = %s", (uid,))
        conn.commit()
    print("\n[CLEANUP] Removed test citizen + mukhtar + all related data")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Passport New E2E Integration Test")
    print(f"  Target: {BASE_URL}")
    print(f"  Service type: {SERVICE_TYPE}")
    print("  Expected path: pending_mukhtar (no MRZ, mukhtar required)")
    print("=" * 60)

    wait_for_gateway()
    flush_rate_limits()

    token, user_id = register_and_login()
    mukhtar_id = seed_mukhtar()

    try:
        case = step_create_case(token)
        case_id = case["id"]

        step_required_docs(token, case_id)
        step_upload_three_docs(token, case_id)
        step_liveness_flow(token, case_id)
        step_submit(token, case_id)

        final_case = step_wait_for_pipeline(token, case_id)

        step_assert_pending_mukhtar(final_case, mukhtar_id, user_id)
        step_no_mrz_for_passport_new(case_id)

        print("\n" + "=" * 60)
        print("  ALL PASSPORT NEW E2E TESTS PASSED")
        print("=" * 60)
    finally:
        cleanup(user_id, mukhtar_id)
        flush_rate_limits()


if __name__ == "__main__":
    main()
