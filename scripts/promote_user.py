#!/usr/bin/env python3
"""Promote a user to admin or clerk role.

Usage:
    python scripts/promote_user.py admin user@example.com
    python scripts/promote_user.py clerk user@example.com
"""

import sys
import subprocess

VALID_ROLES = ("admin", "clerk", "citizen")

def main():
    if len(sys.argv) != 3 or sys.argv[1] not in VALID_ROLES:
        print(f"Usage: python {sys.argv[0]} <{'/'.join(VALID_ROLES)}> <email>")
        sys.exit(1)

    role, email = sys.argv[1], sys.argv[2]

    sql = f"UPDATE users SET role = '{role}' WHERE email = '{email}' RETURNING email, role;"
    result = subprocess.run(
        ["docker", "compose", "exec", "-T", "db", "psql", "-U", "docflow", "-d", "docflow", "-c", sql],
        capture_output=True, text=True,
    )

    if "UPDATE 0" in result.stdout or "(0 rows)" in result.stdout:
        print(f"No user found with email: {email}")
        sys.exit(1)
    elif role in result.stdout:
        print(f"Done — {email} is now '{role}'")
    else:
        print(result.stdout or result.stderr)

if __name__ == "__main__":
    main()