"""Wipe demo data without dropping the schema.

Removes the three demo users (demo_citizen / demo_mukhtar /
demo_admin) and every case, document, OCR/face/registry result,
audit log, payment, email-verification, and password-reset row
that belongs to them. Schema, migrations, and any other users
are untouched.

Use between demo runs to re-seed cleanly:

    python -m scripts.reset_demo && python -m scripts.seed_demo
"""

from __future__ import annotations

import sys
import psycopg2

DB_DSN = "host=localhost port=5432 dbname=docflow user=docflow password=docflow"

DEMO_EMAILS = (
    "demo_citizen@docflow.example.com",
    "demo_mukhtar@docflow.example.com",
    "demo_admin@docflow.example.com",
)


def main():
    with psycopg2.connect(DB_DSN) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM users WHERE email = ANY(%s)", (list(DEMO_EMAILS),)
        )
        user_ids = [str(r[0]) for r in cur.fetchall()]
        if not user_ids:
            print("[skip] no demo users found")
            return

        cur.execute("SELECT id FROM cases WHERE user_id = ANY(%s)", (user_ids,))
        case_ids = [str(r[0]) for r in cur.fetchall()]

        # Order matters: child rows before parents to satisfy FKs.
        # audit_logs reference cases AND users, so wipe both filters.
        if case_ids:
            cur.execute(
                "DELETE FROM audit_logs WHERE case_id = ANY(%s)", (case_ids,)
            )
            cur.execute(
                "DELETE FROM face_results WHERE case_id = ANY(%s)", (case_ids,)
            )
            cur.execute(
                """DELETE FROM ocr_results
                    WHERE document_id IN (
                      SELECT id FROM documents WHERE case_id = ANY(%s)
                    )""",
                (case_ids,),
            )
            cur.execute(
                "DELETE FROM documents WHERE case_id = ANY(%s)", (case_ids,)
            )
            cur.execute(
                "DELETE FROM payments WHERE case_id = ANY(%s)", (case_ids,)
            )
            cur.execute("DELETE FROM cases WHERE id = ANY(%s)", (case_ids,))

        cur.execute("DELETE FROM audit_logs WHERE user_id = ANY(%s)", (user_ids,))
        cur.execute(
            "DELETE FROM email_verification_tokens WHERE user_id = ANY(%s)",
            (user_ids,),
        )
        cur.execute(
            "DELETE FROM password_reset_tokens WHERE user_id = ANY(%s)",
            (user_ids,),
        )
        cur.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
        conn.commit()

    print(f"[ok] wiped {len(user_ids)} demo users + {len(case_ids)} cases")


if __name__ == "__main__":
    try:
        main()
    except psycopg2.Error as e:
        sys.exit(f"[fail] {e}")
