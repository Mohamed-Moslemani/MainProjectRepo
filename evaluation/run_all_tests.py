"""
Run all E2E integration test suites.

Usage:
    1. docker compose --env-file .env.dev up -d --build
    2. pip install requests psycopg2-binary redis
    3. python -m evaluation.run_all_tests
"""

import os
import subprocess
import sys
import time

import redis

SUITES = [
    ("Auth Flow", "evaluation.test_auth_e2e"),
    ("Case Lifecycle", "evaluation.test_cases_e2e"),
    ("Payment Flow", "evaluation.test_payment_e2e"),
    ("Admin/Clerk Flow", "evaluation.test_admin_e2e"),
    ("Security & Rate Limiting", "evaluation.test_security_e2e"),
]

REDIS_HOST = "localhost"
REDIS_PORT = 6380

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def flush_redis():
    """Flush ALL Redis data to clear rate limits between suites."""
    try:
        r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
        r.flushall()
        r.close()
    except Exception as e:
        print(f"  [WARN] Redis flush failed: {e}")


def main():
    print("=" * 60)
    print("  DocFlow Lebanon — Full E2E Test Suite")
    print("=" * 60)

    results = []
    start = time.time()

    for name, module in SUITES:
        # Flush Redis before EVERY suite
        flush_redis()
        time.sleep(1)

        print(f"\n{'─' * 60}")
        print(f"  Running: {name}")
        print(f"{'─' * 60}")

        result = subprocess.run(
            [sys.executable, "-m", module],
            cwd=PROJECT_DIR,
        )

        passed = result.returncode == 0
        results.append((name, passed))

        if not passed:
            print(f"\n  *** {name} FAILED ***")

    # Final cleanup
    flush_redis()

    elapsed = time.time() - start

    # Summary
    print(f"\n{'=' * 60}")
    print("  TEST RESULTS SUMMARY")
    print(f"{'=' * 60}")

    all_passed = True
    for name, passed in results:
        status = "PASSED" if passed else "FAILED"
        icon = "✓" if passed else "✗"
        print(f"  {icon} {name}: {status}")
        if not passed:
            all_passed = False

    print(f"\n  Time: {elapsed:.1f}s")
    print(f"  {sum(p for _, p in results)}/{len(results)} suites passed")
    print(f"{'=' * 60}")

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    main()