# Load testing

Baseline: 50 virtual users, 5/s spawn rate, 2-minute window. Mock
mode for OCR/Face is mandatory — real provider calls would dominate
the histogram and bill the prod accounts at ~$0.0015 per call.

## Quick start

```bash
# 1. Bring up the stack in mock mode
OCR_MOCK_MODE=true FACE_MOCK_MODE=true docker compose up -d

# 2. Pre-seed citizen accounts (bcrypt is expensive, do it once)
python load/seed_users.py --base http://localhost:8000 --count 20

# 3. Optional — seed an admin user (or set LOAD_ADMIN_EMAIL/PASSWORD
#    to point at an existing one)

# 4. Run the baseline headlessly
locust -f load/locustfile.py --host=http://localhost:8000 \
       --headless -u 50 -r 5 -t 2m \
       --csv=load/baseline --csv-full-history
```

The `@events.quitting` hook in `locustfile.py` enforces these SLOs
and exits non-zero on regression:

| Endpoint              | p95 budget | Notes                          |
| --------------------- | ---------- | ------------------------------ |
| `auth:login`          | 800 ms     | bcrypt-bound                   |
| `cases:list`          | 250 ms     | indexed by owner_id            |
| `cases:create_draft`  | 500 ms     | uses Idempotency-Key           |
| `health:ready`        | 50 ms      | LB ping                        |
| `admin:queue`         | 400 ms     | filtered by status             |

Error rate budget: 1%.

## Interpreting results

`load/baseline_stats.csv` is the per-endpoint summary, including
median, p95, p99, throughput, and failure count. Check this in to
the repo (or upload as a CI artifact) so future runs have a
reference baseline.

If `auth:login` p95 starts climbing, the most likely cause is
bcrypt cost or a regression in the index on `users.email`. If
`cases:list` p95 climbs, check the case-list query plan first
(`EXPLAIN ANALYZE`) — pagination is supposed to use the
`(owner_id, created_at DESC)` index.
