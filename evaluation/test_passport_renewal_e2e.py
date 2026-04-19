"""End-to-end integration test for the passport_renewal service type.

Exercises the face-match flow, MRZ parsing path, and mukhtar auto-assignment
— none of which the id_new E2E test covers.

Runs against the full Docker Compose stack with AI mock mode ON
(OCR_MOCK_MODE=true FACE_MOCK_MODE=true), so there are no Google Cloud
Vision or AWS Rekognition charges and results are deterministic.

Usage:
    1. OCR_MOCK_MODE=true FACE_MOCK_MODE=true \
       docker compose --env-file .env.dev up -d --build ocr face gateway
    2. python -m evaluation.test_passport_renewal_e2e

Flow:
    register citizen → seed mukhtar in same district → login →
    create passport_renewal case → upload passport + civil registry →
    liveness create-session → liveness get-results (mock SUCCEEDED +
    similarity 95) → submit → poll for final status →
    assert OCR/Face/Reconciliation/Risk records present →
    assert mukhtar auto-assigned → assert final status = pending_mukhtar
"""

import os
import sys
import time
import uuid

import psycopg2
import requests

# ── Configuration ─────────────────────────────────────────────────────────

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"
DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

TEST_EMAIL = f"passport_test_{uuid.uuid4().hex[:8]}@example.com"
MUKHTAR_EMAIL = f"mukhtar_{uuid.uuid4().hex[:8]}@example.com"
TEST_PASSWORD = "Str0ng!Pass#1"
SERVICE_TYPE = "passport_renewal"
REGISTRY_PLACE = "Beirut"
MUNICIPALITY = "Beirut Central"

# Declared fields — aligned with the mock OCR passport + civil registry fixtures
# so reconciliation scores high and the case ends up at pending_mukhtar
# rather than rejected.
DECLARED_FIELDS = {
    "full_name": "Mohamed Saad",
    "father_name": "Ali Saad",
    "mother_name": "Fatima Hassan",
    "date_of_birth": "15/06/1995",
    "place_of_birth": "Beirut",
    "old_passport_number": "LB1234567",
    "passport_type": "ordinary",
    "registry_number": "12345",
    "registry_place": REGISTRY_PLACE,
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
    """Minimal valid 1x1 JPEG — contents don't matter in mock mode."""
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
    """Register a test citizen, verify email via DB, login, return (access_token, user_id)."""
    r = requests.post(f"{API}/auth/register", json={
        "email": TEST_EMAIL,
        "password": TEST_PASSWORD,
        "full_name": "Mohamed Saad",
        "father_name": "Ali Saad",
        "mother_name": "Fatima Hassan",
        "date_of_birth": "1995-06-15",
        "place_of_birth": "Beirut",
        "gender": "male",
        "registry_number": "12345",
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
    """Insert a mukhtar user directly in the DB (matching the test citizen's district)."""
    from passlib.hash import bcrypt
    mukhtar_id = str(uuid.uuid4())
    password_hash = bcrypt.hash(TEST_PASSWORD)

    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO users (
                id, email, password_hash, full_name, role, email_verified,
                registry_place, municipality, registry_number, created_at
            ) VALUES (%s, %s, %s, %s, 'mukhtar', TRUE, %s, %s, '99999', NOW())
            """,
            (
                mukhtar_id, MUKHTAR_EMAIL, password_hash, "Mukhtar Beirut",
                REGISTRY_PLACE, MUNICIPALITY,
            ),
        )
        conn.commit()
    print(f"  [SEED] mukhtar id={mukhtar_id[:8]}... at {MUNICIPALITY}/{REGISTRY_PLACE}")
    return mukhtar_id


def auth_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ── Steps ─────────────────────────────────────────────────────────────────

def step_create_case(token: str) -> dict:
    print("\n--- Step 1: Create passport_renewal case ---")
    r = requests.post(
        f"{API}/cases",
        json={
            "service_type": SERVICE_TYPE,
            "declared_fields": {},  # filled in at submit
        },
        headers=auth_headers(token),
    )
    assert_status("POST /cases", r, 201)
    body = r.json()
    assert_eq("status is draft", body["status"], "draft")
    assert_eq("service_type matches", body["service_type"], SERVICE_TYPE)
    return body


def step_required_docs_match_policy(token: str, case_id: str):
    print("\n--- Step 2: Required documents include passport + selfie ---")
    r = requests.get(f"{API}/cases/{case_id}/required-documents", headers=auth_headers(token))
    assert_status("GET /required-documents", r, 200)
    body = r.json()
    docs = body["required_documents"]
    assert_truthy("old_passport_data_page required", "old_passport_data_page" in docs)
    assert_truthy("civil_registry_extract required", "civil_registry_extract" in docs)
    assert_truthy("selfie required", "selfie" in docs)
    assert_truthy("liveness_capture required", "liveness_capture" in docs)


def step_upload_documents(token: str, case_id: str):
    print("\n--- Step 3: Upload passport + civil registry ---")
    img = create_test_image()
    for doc_type in ("old_passport_data_page", "civil_registry_extract"):
        r = requests.post(
            f"{API}/cases/{case_id}/documents",
            files={"file": (f"{doc_type}.jpg", img, "image/jpeg")},
            data={"document_type": doc_type},
            headers=auth_headers(token),
        )
        assert_status(f"upload {doc_type}", r, 200)


def step_liveness_flow(token: str, case_id: str) -> str:
    print("\n--- Step 4: Liveness session (mock returns SUCCEEDED) ---")

    r = requests.post(
        f"{API}/liveness/create-session",
        json={"case_id": case_id},
        headers=auth_headers(token),
    )
    assert_status("POST /liveness/create-session", r, 200)
    session_id = r.json()["session_id"]
    assert_truthy("session_id starts with 'mock-'", session_id.startswith("mock-"))

    r = requests.post(
        f"{API}/liveness/get-results",
        json={"case_id": case_id, "session_id": session_id},
        headers=auth_headers(token),
    )
    assert_status("POST /liveness/get-results", r, 200)
    body = r.json()
    assert_eq("liveness status SUCCEEDED", body["status"], "SUCCEEDED")
    assert_eq("liveness_passed", body["liveness_passed"], True)
    assert_truthy("similarity_score set", body.get("similarity_score") is not None)
    return session_id


def step_completeness_after_liveness(token: str, case_id: str):
    print("\n--- Step 5: Completeness with liveness substitutes for selfie ---")
    r = requests.get(f"{API}/cases/{case_id}/completeness", headers=auth_headers(token))
    assert_status("GET /completeness", r, 200)
    body = r.json()
    assert_eq("case is complete", body["complete"], True)


def step_submit(token: str, case_id: str):
    print("\n--- Step 6: Submit case ---")
    r = requests.post(
        f"{API}/cases/{case_id}/submit",
        json={"declared_fields": DECLARED_FIELDS},
        headers=auth_headers(token),
    )
    assert_status("POST /submit", r, 200)


def step_wait_for_pipeline(token: str, case_id: str, timeout: int = 60) -> dict:
    """Poll the case until it reaches a final-ish status (not submitted or validated)."""
    print(f"\n--- Step 7: Wait for pipeline (max {timeout}s) ---")
    deadline = time.time() + timeout
    transient = {"submitted", "validated"}
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


def step_assert_pipeline_artifacts(case_body: dict, user_id: str):
    print("\n--- Step 8: Pipeline produced all AI artifacts ---")

    assert_truthy("liveness_result populated", case_body.get("liveness_result"))
    assert_eq(
        "liveness_result.status",
        case_body["liveness_result"]["status"],
        "SUCCEEDED",
    )

    assert_truthy("reconciliation_result populated", case_body.get("reconciliation_result"))
    recon = case_body["reconciliation_result"]
    assert_truthy("integrity_score present", "integrity_score" in recon)
    assert_truthy("validation_result present", "validation_result" in recon)
    # integrity > 0 catches the silent PATTERN_MAP mismatch bug — if the
    # field_extractor doesn't have patterns for the concrete DocumentType,
    # no fields get extracted and integrity collapses to 0.
    assert_truthy(f"integrity > 0 (got {recon['integrity_score']})", recon["integrity_score"] > 0)

    assert_truthy("risk_result populated", case_body.get("risk_result"))
    risk = case_body["risk_result"]
    assert_truthy("risk_score present", "risk_score" in risk)
    assert_truthy("routing present", "routing" in risk)
    assert_truthy("breakdown present", "breakdown" in risk)
    # Passport should land at auto_approve-level risk with clean inputs;
    # mukhtar_required still routes it to pending_mukhtar, but the score
    # itself must be low enough that nothing else would have gone wrong.
    assert_truthy(f"risk_score reasonable (got {risk['risk_score']})", risk["risk_score"] < 40)

    # OCRResult + FaceResult rows directly in DB
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

    assert_truthy(f"OCRResult row exists (count={ocr_count})", ocr_count >= 1)
    assert_truthy(f"FaceResult row exists (count={face_count})", face_count == 1)


def step_assert_final_status_and_mukhtar(case_body: dict, mukhtar_id: str):
    print("\n--- Step 9: Final status = pending_mukhtar + auto-assigned ---")
    assert_eq("final status", case_body["status"], "pending_mukhtar")
    assert_eq("mukhtar auto-assigned to our seeded mukhtar",
              case_body.get("mukhtar_id"), mukhtar_id)


def step_audit_logs_are_reproducible(case_id: str):
    """Audit logs must capture enough detail to re-derive every AI decision.

    This guards against regressions where log_action() is called with only
    summary fields — we want auditors to replay the entire pipeline.
    """
    print("\n--- Step 10: Audit logs contain full AI breakdown ---")
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT action, details FROM audit_logs WHERE case_id = %s ORDER BY created_at",
            (case_id,),
        )
        rows = cur.fetchall()

    by_action: dict[str, list[dict]] = {}
    for action, details in rows:
        by_action.setdefault(action, []).append(details or {})

    assert_truthy("ocr_completed log present", by_action.get("ocr_completed"))
    ocr_log = by_action["ocr_completed"][0]
    assert_truthy("ocr log has extracted_fields", "extracted_fields" in ocr_log)
    assert_truthy("ocr log has confidence_scores", "confidence_scores" in ocr_log)
    assert_truthy("ocr log has quality", "quality" in ocr_log)

    assert_truthy("face_verification_completed log present", by_action.get("face_verification_completed"))
    face_log = by_action["face_verification_completed"][0]
    assert_truthy("face log has similarity_score", "similarity_score" in face_log)
    assert_truthy("face log has liveness_score", "liveness_score" in face_log)
    assert_truthy("face log has decision", "decision" in face_log)

    assert_truthy("reconciliation_completed log present", by_action.get("reconciliation_completed"))
    recon_log = by_action["reconciliation_completed"][0]
    assert_truthy("recon log has field_results", "field_results" in recon_log)
    assert_truthy("recon log has declared_fields", "declared_fields" in recon_log)
    assert_truthy("recon log has integrity_score", "integrity_score" in recon_log)

    assert_truthy("risk_evaluated log present", by_action.get("risk_evaluated"))
    risk_log = by_action["risk_evaluated"][0]
    assert_truthy("risk log has breakdown", "breakdown" in risk_log)
    assert_truthy("risk log has inputs", "inputs" in risk_log)
    assert_truthy("risk log has routing", "routing" in risk_log)
    inputs = risk_log["inputs"]
    for key in ("ocr_avg_confidence", "face_similarity", "liveness_score",
                "reconciliation_integrity", "service_type", "mismatch_count"):
        assert_truthy(f"risk inputs include {key}", key in inputs)

    assert_truthy("decision_made log present", by_action.get("decision_made"))
    decision_log = by_action["decision_made"][0]
    assert_truthy("decision log has final_status", "final_status" in decision_log)
    assert_truthy("decision log has pipeline_duration_seconds", "pipeline_duration_seconds" in decision_log)


def step_tracking_shows_full_history(token: str, case_id: str):
    print("\n--- Step 10: Tracking shows full pipeline history ---")
    r = requests.get(f"{API}/cases/{case_id}/tracking", headers=auth_headers(token))
    assert_status("GET /tracking", r, 200)
    events = [e["status"] for e in r.json()["events"]]
    assert_truthy("submitted event", "submitted" in events)
    assert_truthy("validated event", "validated" in events)
    assert_truthy("risk_evaluated event", "risk_evaluated" in events)
    assert_truthy("pending_mukhtar event", "pending_mukhtar" in events)


# ── Cleanup ───────────────────────────────────────────────────────────────

def cleanup(user_id: str, mukhtar_id: str):
    with db_conn() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit_logs WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM audit_logs WHERE user_id IN (%s, %s)", (user_id, mukhtar_id))
        # face_results references documents — drop it before documents
        cur.execute("DELETE FROM face_results WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM ocr_results WHERE document_id IN (SELECT d.id FROM documents d JOIN cases c ON d.case_id = c.id WHERE c.user_id = %s)", (user_id,))
        cur.execute("DELETE FROM documents WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM payments WHERE case_id IN (SELECT id FROM cases WHERE user_id = %s)", (user_id,))
        cur.execute("DELETE FROM cases WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM email_verification_tokens WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM password_reset_tokens WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM users WHERE id IN (%s, %s)", (user_id, mukhtar_id))
        conn.commit()
    print(f"\n[CLEANUP] Removed test citizen + mukhtar + all related data")


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  Passport Renewal E2E Integration Test")
    print(f"  Target: {BASE_URL}")
    print(f"  Service type: {SERVICE_TYPE}")
    print(f"  Mock mode expected: OCR_MOCK_MODE + FACE_MOCK_MODE = true")
    print("=" * 60)

    wait_for_gateway()
    flush_rate_limits()

    token, user_id = register_and_login()
    mukhtar_id = seed_mukhtar()

    try:
        case = step_create_case(token)
        case_id = case["id"]

        step_required_docs_match_policy(token, case_id)
        step_upload_documents(token, case_id)
        step_liveness_flow(token, case_id)
        step_completeness_after_liveness(token, case_id)
        step_submit(token, case_id)

        final_case = step_wait_for_pipeline(token, case_id)

        step_assert_pipeline_artifacts(final_case, user_id)
        step_assert_final_status_and_mukhtar(final_case, mukhtar_id)
        step_audit_logs_are_reproducible(case_id)
        step_tracking_shows_full_history(token, case_id)

        print("\n" + "=" * 60)
        print("  ALL PASSPORT RENEWAL E2E TESTS PASSED")
        print("=" * 60)
    finally:
        cleanup(user_id, mukhtar_id)
        flush_rate_limits()


if __name__ == "__main__":
    main()
