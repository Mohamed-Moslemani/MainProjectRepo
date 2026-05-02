"""Mukhtar attestation contract test.

Catches the regression class where the SPA's API wrapper drops the
three-part attestation booleans (residence/photo/presence) before the
POST hits the gateway. The backend rejects partial attestations with
400 — this test asserts both shapes (full = 200, partial = 400) so a
future refactor can't silently break passport approvals.

Flow:
    seed mukhtar + citizen → run a passport_renewal through the
    pipeline to pending_mukhtar → mukhtar logs in →
        - approve with only 2/3 attestations → assert 400
        - approve with 3/3 attestations → assert 200, status flips
          to approved → payment_pending
"""

import sys
import time
import uuid

import psycopg2
import requests

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"
DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

PASSWORD = "Str0ng!Pass#1"
CITIZEN_EMAIL = f"mukhatt_citizen_{uuid.uuid4().hex[:8]}@example.com"
MUKHTAR_EMAIL = f"mukhatt_mukhtar_{uuid.uuid4().hex[:8]}@example.com"
SERVICE_TYPE = "passport_renewal"
REGISTRY_PLACE = "Beirut"
MUNICIPALITY = "Beirut Central"

DECLARED = {
    "full_name": "Mohamed Saad", "father_name": "Ali Saad",
    "mother_name": "Fatima Hassan", "date_of_birth": "15/06/1995",
    "place_of_birth": "Beirut", "old_passport_number": "LR1234567",
    "passport_type": "ordinary", "registry_number": "12345",
    "registry_place": REGISTRY_PLACE,
    # municipality intentionally omitted from declared_fields — it is
    # not present in any uploaded doc, so reconciliation would mark it
    # as a mismatch and raise the risk score. The mukhtar jurisdiction
    # check at the decide endpoint falls back to registry_place which
    # both the citizen and seeded mukhtar share.
    "renewal_reason": "expired", "passport_validity_years": 5,
}


def db():
    return psycopg2.connect(DB_DSN)


def assert_eq(label, actual, expected):
    if actual != expected:
        sys.exit(f"[FAIL] {label}: expected {expected!r}, got {actual!r}")
    print(f"  [PASS] {label}")


def assert_status(label, resp, expected):
    if resp.status_code != expected:
        sys.exit(f"[FAIL] {label}: expected {expected}, got {resp.status_code} — {resp.text[:200]}")
    print(f"  [PASS] {label} -> {expected}")


def jpeg() -> bytes:
    return bytes.fromhex(
        "ffd8ffe000104a46494600010100000100010000ffdb004300080606070605"
        "0808070709090808a0c140d0c0b0b0c1912130f141d1a1f1e1d1a1c1c20242e"
        "2720222c231c1c2837292c30313434341f273940383239333432ffc0000b08"
        "0001000101011100ffc4001f0000010501010101010101000000000000000"
        "00102030405060708090a0bffc400b51000020103030204030505040400000"
        "1027d010203000411051221314106135161073241814591a1082342b1c115"
        "521d1f02433627282090a161718191a25262728292a3435363738393a4344"
        "45464748494a535455565758595a636465666768696a737475767778797a8"
        "3848586878889899a99a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b"
        "4b5b6b7b8b9babc2c3c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2ffda000"
        "8010100003f007b941100000000000000ffd9"
    )


def hdr(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def wait_gateway(t=60):
    deadline = time.time() + t
    while time.time() < deadline:
        try:
            if requests.get(f"{BASE_URL}/health", timeout=3).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(2)
    sys.exit("[FAIL] gateway not healthy")


def seed_mukhtar() -> str:
    from passlib.hash import bcrypt
    mid = str(uuid.uuid4())
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO users (
                 id, email, password_hash, full_name, role, email_verified,
                 registry_place, municipality, registry_number, created_at
               ) VALUES (%s,%s,%s,%s,'mukhtar',TRUE,%s,%s,'99999',NOW())""",
            (mid, MUKHTAR_EMAIL, bcrypt.hash(PASSWORD), "Mukhtar Beirut",
             REGISTRY_PLACE, MUNICIPALITY),
        )
        conn.commit()
    return mid


def register_login() -> tuple[str, str]:
    r = requests.post(f"{API}/auth/register", json={
        "email": CITIZEN_EMAIL, "password": PASSWORD,
        "full_name": "Mohamed Saad", "father_name": "Ali Saad",
        "mother_name": "Fatima Hassan", "date_of_birth": "1995-06-15",
        "place_of_birth": "Beirut", "gender": "male",
        "registry_number": "12345", "registry_place": REGISTRY_PLACE,
    })
    assert_status("register citizen", r, 201)
    user_id = r.json()["id"]
    with db() as conn, conn.cursor() as cur:
        cur.execute("UPDATE users SET email_verified=TRUE WHERE id=%s", (user_id,))
        conn.commit()
    r = requests.post(f"{API}/auth/login", json={"email": CITIZEN_EMAIL, "password": PASSWORD})
    assert_status("login citizen", r, 200)
    return r.json()["access_token"], user_id


def drive_to_pending_mukhtar(citizen_id: str, mukhtar_id: str) -> str:
    """Bypass the AI pipeline and inject a case directly at PENDING_MUKHTAR.

    This test exists to lock down the *mukhtar attestation contract*,
    not to retest the pipeline. Driving via the real submit endpoint
    couples the test to risk-score thresholds, OCR mock fixtures, and
    registry seed data — every change to those would flake this test.
    """
    case_id = str(uuid.uuid4())
    tracking_id = f"DFL-MAT{uuid.uuid4().hex[:6].upper()}"
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO cases (
                id, tracking_id, user_id, mukhtar_id, service_type,
                status, declared_fields, status_history, created_at, updated_at
            ) VALUES (
                %s, %s, %s, %s, %s, 'pending_mukhtar',
                %s::jsonb, '[]'::jsonb, NOW(), NOW()
            )
            """,
            (case_id, tracking_id, citizen_id, mukhtar_id, SERVICE_TYPE,
             __import__("json").dumps(DECLARED)),
        )
        conn.commit()
    print(f"  [seed] case {case_id[:8]}… injected at pending_mukhtar")
    return case_id


def test_partial_attestation_rejected(case_id: str, mukhtar_token: str):
    print("\n--- Step: 2/3 attestations → 400 ---")
    r = requests.post(f"{API}/mukhtar/cases/{case_id}/decide",
                      headers=hdr(mukhtar_token), json={
                          "decision": "approve",
                          "residence_verified": True,
                          "photo_verified": True,
                          "presence_verified": False,
                          "residence_notes": "known to me 12+ years",
                      })
    assert_status("partial attestation rejected", r, 400)
    detail = r.json().get("detail", "")
    assert "presence" in detail.lower(), f"detail must mention missing field — got {detail!r}"
    print("  [PASS] detail names the missing attestation")


def test_full_attestation_approves(case_id: str, mukhtar_token: str, citizen_token: str):
    print("\n--- Step: 3/3 attestations → 200 + status flips ---")
    r = requests.post(f"{API}/mukhtar/cases/{case_id}/decide",
                      headers=hdr(mukhtar_token), json={
                          "decision": "approve",
                          "residence_verified": True,
                          "photo_verified": True,
                          "presence_verified": True,
                          "residence_notes": "known to me 12+ years",
                          "notes": "stamped",
                      })
    assert_status("full attestation accepted", r, 200)

    body = requests.get(f"{API}/cases/{case_id}", headers=hdr(citizen_token)).json()
    # Approve auto-chains to payment_pending
    if body["status"] not in ("approved", "payment_pending"):
        sys.exit(f"[FAIL] expected approved|payment_pending, got {body['status']}")
    print(f"  [PASS] case advanced to {body['status']}")

    # Audit trail must record all three attestations
    with db() as conn, conn.cursor() as cur:
        cur.execute(
            """SELECT details FROM audit_logs
                WHERE case_id=%s AND action='mukhtar_decision'""", (case_id,))
        rows = [r[0] for r in cur.fetchall()]
    if not rows or "attestations" not in (rows[0] or {}):
        sys.exit("[FAIL] audit log missing attestations dict")
    attest = rows[0]["attestations"]
    for k in ("residence_verified", "photo_verified", "presence_verified"):
        if not attest.get(k):
            sys.exit(f"[FAIL] audit log attestations.{k} not True")
    print("  [PASS] audit log records all three attestations")


def cleanup(citizen_id: str, mukhtar_id: str):
    with db() as conn, conn.cursor() as cur:
        for uid in (citizen_id, mukhtar_id):
            cur.execute(
                "DELETE FROM audit_logs WHERE case_id IN (SELECT id FROM cases WHERE user_id=%s)",
                (uid,))
            cur.execute("DELETE FROM audit_logs WHERE user_id=%s", (uid,))
            cur.execute(
                "DELETE FROM face_results WHERE case_id IN (SELECT id FROM cases WHERE user_id=%s)",
                (uid,))
            cur.execute(
                "DELETE FROM ocr_results WHERE document_id IN (SELECT d.id FROM documents d JOIN cases c ON d.case_id=c.id WHERE c.user_id=%s)",
                (uid,))
            cur.execute(
                "DELETE FROM documents WHERE case_id IN (SELECT id FROM cases WHERE user_id=%s)",
                (uid,))
            cur.execute(
                "DELETE FROM payments WHERE case_id IN (SELECT id FROM cases WHERE user_id=%s)",
                (uid,))
            cur.execute("DELETE FROM cases WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM email_verification_tokens WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM password_reset_tokens WHERE user_id=%s", (uid,))
            cur.execute("DELETE FROM users WHERE id=%s", (uid,))
        conn.commit()


def main():
    print("=" * 60)
    print("  Mukhtar Attestation E2E (3-part contract)")
    print("=" * 60)

    wait_gateway()
    citizen_token, citizen_id = register_login()
    mukhtar_id = seed_mukhtar()

    try:
        case_id = drive_to_pending_mukhtar(citizen_id, mukhtar_id)
        # Mukhtar logs in
        r = requests.post(f"{API}/auth/login", json={"email": MUKHTAR_EMAIL, "password": PASSWORD})
        assert_status("mukhtar login", r, 200)
        mukhtar_token = r.json()["access_token"]

        test_partial_attestation_rejected(case_id, mukhtar_token)
        test_full_attestation_approves(case_id, mukhtar_token, citizen_token)

        print("\n" + "=" * 60)
        print("  ALL ATTESTATION TESTS PASSED")
        print("=" * 60)
    finally:
        cleanup(citizen_id, mukhtar_id)


if __name__ == "__main__":
    main()
