"""Seed deterministic demo data for the live walkthrough.

Idempotent: safe to re-run. If the demo identities already exist
they're left alone; otherwise this creates:

  citizen      demo_citizen@docflow.example.com        / Demo!Pass#1
  mukhtar      demo_mukhtar@docflow.example.com        / Demo!Pass#1
  clerk/admin  demo_admin@docflow.example.com          / Demo!Pass#1

Plus two in-flight cases on the citizen so the demo can show
both routing branches without 5 minutes of clicking:
  - passport_renewal  → status: pending_mukhtar (mukhtar inbox)
  - id_renewal        → status: payment_pending (Stripe checkout)

Run with the gateway + ocr + face stack already up. In mock mode
(OCR_MOCK_MODE=1 FACE_MOCK_MODE=1) no real API calls happen.

Usage:
    python -m scripts.seed_demo
"""

from __future__ import annotations

import sys
import time
import uuid

import psycopg2
import requests

BASE_URL = "http://localhost:8000"
API = f"{BASE_URL}/api/v1"
DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

CITIZEN_EMAIL = "demo_citizen@docflow.example.com"
MUKHTAR_EMAIL = "demo_mukhtar@docflow.example.com"
ADMIN_EMAIL = "demo_admin@docflow.example.com"
PASSWORD = "Demo!Pass#1"

REGISTRY_PLACE = "Beirut"
MUNICIPALITY = "Beirut Central"

# Identity values that match the OCR mock fixtures so reconciliation
# scores high on submit. Keep in sync with services/ocr/app/services/mocks.py.
DECLARED_PASSPORT = {
    "full_name": "Mohamed Saad",
    "father_name": "Ali Saad",
    "mother_name": "Fatima Hassan",
    "date_of_birth": "15/06/1995",
    "place_of_birth": "Beirut",
    "old_passport_number": "LR1234567",
    "passport_type": "ordinary",
    "registry_number": "12345",
    "registry_place": REGISTRY_PLACE,
    "renewal_reason": "expired",
    "passport_validity_years": 5,
}
DECLARED_ID = {
    "full_name": "Mohamed Saad",
    "father_name": "Ali Saad",
    "mother_name": "Fatima Hassan",
    "date_of_birth": "15/06/1995",
    "registry_number": "12345",
    "address": "Beirut, Lebanon",
    "marital_status": "single",
    "reason_for_renewal": "expired",
}
DECLARED_ID_NEW = {
    "full_name": "Mohamed Saad",
    "father_name": "Ali Saad",
    "mother_name": "Fatima Hassan",
    "date_of_birth": "15/06/1995",
    "place_of_birth": "Beirut",
    "registry_number": "12345",
    "address": "Beirut, Lebanon",
    "marital_status": "single",
}
DECLARED_PASSPORT_NEW = {
    "full_name": "Mohamed Saad",
    "father_name": "Ali Saad",
    "mother_name": "Fatima Hassan",
    "date_of_birth": "15/06/1995",
    "place_of_birth": "Beirut",
    "registry_number": "12345",
    "registry_place": REGISTRY_PLACE,
    "passport_validity_years": 5,
}


def db():
    return psycopg2.connect(DB_DSN)


def gateway_up() -> bool:
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=3)
        return r.status_code == 200
    except requests.RequestException:
        return False


def wait_for_gateway(timeout: int = 60):
    print("[wait] gateway readiness")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if gateway_up():
            print("[ok]   gateway healthy")
            return
        time.sleep(2)
    sys.exit("[fail] gateway not healthy")


def jpeg() -> bytes:
    """Minimal valid 1x1 JPEG. Mock OCR/Face don't read it."""
    # Inline rather than subprocess'ing imagemagick — keeps the seeder
    # dependency-free.
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


def upsert_user(email: str, role: str, full_name: str, **extra) -> str:
    """Insert via /auth/register if missing, return user_id, mark verified."""
    with db() as conn, conn.cursor() as cur:
        cur.execute("SELECT id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
        if row:
            user_id = str(row[0])
            cur.execute(
                "UPDATE users SET email_verified = TRUE WHERE id = %s",
                (user_id,),
            )
            conn.commit()
            print(f"[skip] {role:8s} {email} already exists ({user_id[:8]}…)")
            return user_id

    if role == "citizen":
        r = requests.post(f"{API}/auth/register", json={
            "email": email, "password": PASSWORD,
            "full_name": full_name,
            "father_name": "Ali Saad", "mother_name": "Fatima Hassan",
            "date_of_birth": "1995-06-15", "place_of_birth": "Beirut",
            "gender": "male", "registry_number": "12345",
            "registry_place": REGISTRY_PLACE,
        })
        if r.status_code != 201:
            sys.exit(f"[fail] register {email}: {r.status_code} {r.text[:200]}")
        user_id = r.json()["id"]
        with db() as conn, conn.cursor() as cur:
            cur.execute("UPDATE users SET email_verified=TRUE WHERE id=%s", (user_id,))
            conn.commit()
    else:
        from passlib.hash import bcrypt
        user_id = str(uuid.uuid4())
        with db() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (
                  id, email, password_hash, full_name, role, email_verified,
                  registry_place, municipality, registry_number, created_at
                ) VALUES (%s,%s,%s,%s,%s,TRUE,%s,%s,%s,NOW())
                """,
                (
                    user_id, email, bcrypt.hash(PASSWORD), full_name, role,
                    extra.get("registry_place", REGISTRY_PLACE),
                    extra.get("municipality", MUNICIPALITY),
                    extra.get("registry_number", "99999"),
                ),
            )
            conn.commit()
    print(f"[ok]   {role:8s} {email} ({user_id[:8]}…)")
    return user_id


def login(email: str) -> str:
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD})
    if r.status_code != 200:
        sys.exit(f"[fail] login {email}: {r.status_code} {r.text[:200]}")
    return r.json()["access_token"]


def hdr(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def make_passport_renewal_case(citizen_token: str) -> str:
    """Create + submit a passport_renewal so the orchestrator routes
    it to pending_mukhtar (auto-approve risk + mukhtar_required)."""
    print("[case] passport_renewal → pending_mukhtar")
    r = requests.post(f"{API}/cases", headers=hdr(citizen_token), json={
        "service_type": "passport_renewal", "declared_fields": {},
    })
    case_id = r.json()["id"]

    img = jpeg()
    for doc_type in ("old_passport_data_page", "civil_registry_extract"):
        requests.post(
            f"{API}/cases/{case_id}/documents",
            files={"file": (f"{doc_type}.jpg", img, "image/jpeg")},
            data={"document_type": doc_type},
            headers=hdr(citizen_token),
        )

    sess = requests.post(f"{API}/liveness/create-session",
                        json={"case_id": case_id}, headers=hdr(citizen_token))
    requests.post(f"{API}/liveness/get-results",
                 json={"case_id": case_id, "session_id": sess.json()["session_id"]},
                 headers=hdr(citizen_token))

    requests.post(f"{API}/cases/{case_id}/submit",
                 json={"declared_fields": DECLARED_PASSPORT},
                 headers=hdr(citizen_token))

    deadline = time.time() + 60
    while time.time() < deadline:
        body = requests.get(f"{API}/cases/{case_id}", headers=hdr(citizen_token)).json()
        if body["status"] not in ("submitted", "validated", "draft"):
            print(f"       case {case_id[:8]}… → {body['status']}")
            return case_id
        time.sleep(1)
    print(f"       [warn] case {case_id[:8]}… did not finish in 60s")
    return case_id


def make_id_renewal_case(citizen_token: str, mukhtar_id: str) -> str:
    """Create + submit + advance an id_renewal all the way through the
    pipeline. id_renewal auto-approves on clean reconciliation, lands
    at approved → payment_pending. No mukhtar step."""
    print("[case] id_renewal → payment_pending")
    r = requests.post(f"{API}/cases", headers=hdr(citizen_token), json={
        "service_type": "id_renewal", "declared_fields": {},
    })
    case_id = r.json()["id"]

    img = jpeg()
    for doc_type in ("old_id_front", "old_id_back", "civil_registry_extract"):
        requests.post(
            f"{API}/cases/{case_id}/documents",
            files={"file": (f"{doc_type}.jpg", img, "image/jpeg")},
            data={"document_type": doc_type},
            headers=hdr(citizen_token),
        )

    sess = requests.post(f"{API}/liveness/create-session",
                        json={"case_id": case_id}, headers=hdr(citizen_token))
    requests.post(f"{API}/liveness/get-results",
                 json={"case_id": case_id, "session_id": sess.json()["session_id"]},
                 headers=hdr(citizen_token))

    requests.post(f"{API}/cases/{case_id}/submit",
                 json={"declared_fields": DECLARED_ID},
                 headers=hdr(citizen_token))

    deadline = time.time() + 60
    while time.time() < deadline:
        body = requests.get(f"{API}/cases/{case_id}", headers=hdr(citizen_token)).json()
        if body["status"] in ("payment_pending", "approved", "rejected", "need_info"):
            print(f"       case {case_id[:8]}… → {body['status']}")
            return case_id
        time.sleep(1)
    print(f"       [warn] case {case_id[:8]}… did not finish in 60s")
    return case_id


def make_id_new_case(citizen_token: str) -> str:
    """Create + submit an id_new case. First-time applicant: only the
    civil-registry extract is needed. Auto-approves on clean
    reconciliation → payment_pending."""
    print("[case] id_new → payment_pending")
    r = requests.post(f"{API}/cases", headers=hdr(citizen_token), json={
        "service_type": "id_new", "declared_fields": {},
    })
    case_id = r.json()["id"]

    img = jpeg()
    requests.post(
        f"{API}/cases/{case_id}/documents",
        files={"file": ("civil_registry_extract.jpg", img, "image/jpeg")},
        data={"document_type": "civil_registry_extract"},
        headers=hdr(citizen_token),
    )

    sess = requests.post(f"{API}/liveness/create-session",
                        json={"case_id": case_id}, headers=hdr(citizen_token))
    requests.post(f"{API}/liveness/get-results",
                 json={"case_id": case_id, "session_id": sess.json()["session_id"]},
                 headers=hdr(citizen_token))

    requests.post(f"{API}/cases/{case_id}/submit",
                 json={"declared_fields": DECLARED_ID_NEW},
                 headers=hdr(citizen_token))

    deadline = time.time() + 60
    while time.time() < deadline:
        body = requests.get(f"{API}/cases/{case_id}", headers=hdr(citizen_token)).json()
        if body["status"] in ("payment_pending", "approved", "rejected", "need_info"):
            print(f"       case {case_id[:8]}… → {body['status']}")
            return case_id
        time.sleep(1)
    print(f"       [warn] case {case_id[:8]}… did not finish in 60s")
    return case_id


def make_passport_new_case(citizen_token: str) -> str:
    """Create + submit a passport_new case. First-time passport applicant:
    needs national_id_front + back + civil_registry_extract. mukhtar_required
    in the policy → routes to pending_mukhtar."""
    print("[case] passport_new → pending_mukhtar")
    r = requests.post(f"{API}/cases", headers=hdr(citizen_token), json={
        "service_type": "passport_new", "declared_fields": {},
    })
    case_id = r.json()["id"]

    img = jpeg()
    for doc_type in ("national_id_front", "national_id_back", "civil_registry_extract"):
        requests.post(
            f"{API}/cases/{case_id}/documents",
            files={"file": (f"{doc_type}.jpg", img, "image/jpeg")},
            data={"document_type": doc_type},
            headers=hdr(citizen_token),
        )

    sess = requests.post(f"{API}/liveness/create-session",
                        json={"case_id": case_id}, headers=hdr(citizen_token))
    requests.post(f"{API}/liveness/get-results",
                 json={"case_id": case_id, "session_id": sess.json()["session_id"]},
                 headers=hdr(citizen_token))

    requests.post(f"{API}/cases/{case_id}/submit",
                 json={"declared_fields": DECLARED_PASSPORT_NEW},
                 headers=hdr(citizen_token))

    deadline = time.time() + 60
    while time.time() < deadline:
        body = requests.get(f"{API}/cases/{case_id}", headers=hdr(citizen_token)).json()
        if body["status"] not in ("submitted", "validated", "risk_evaluated", "draft"):
            print(f"       case {case_id[:8]}… → {body['status']}")
            return case_id
        time.sleep(1)
    print(f"       [warn] case {case_id[:8]}… did not finish in 60s")
    return case_id


def main():
    wait_for_gateway()

    citizen_id = upsert_user(CITIZEN_EMAIL, "citizen", "Mohamed Saad")
    mukhtar_id = upsert_user(
        MUKHTAR_EMAIL, "mukhtar", "Mukhtar Demo",
        registry_place=REGISTRY_PLACE, municipality=MUNICIPALITY,
    )
    upsert_user(ADMIN_EMAIL, "clerk", "Demo Admin")

    citizen_token = login(CITIZEN_EMAIL)
    case_passport_renewal = make_passport_renewal_case(citizen_token)
    case_id_renewal = make_id_renewal_case(citizen_token, mukhtar_id)
    case_id_new = make_id_new_case(citizen_token)
    case_passport_new = make_passport_new_case(citizen_token)

    print()
    print("─" * 60)
    print("  DEMO READY")
    print("─" * 60)
    print(f"  citizen    {CITIZEN_EMAIL:32s}  pwd: {PASSWORD}")
    print(f"  mukhtar    {MUKHTAR_EMAIL:32s}  pwd: {PASSWORD}")
    print(f"  admin      {ADMIN_EMAIL:32s}  pwd: {PASSWORD}")
    print()
    print(f"  id_new           case: {case_id_new}")
    print(f"  id_renewal       case: {case_id_renewal}")
    print(f"  passport_new     case: {case_passport_new}")
    print(f"  passport_renewal case: {case_passport_renewal}")
    print("─" * 60)


if __name__ == "__main__":
    main()
