# Production-readiness audit — 2026-05-02

Two-hour autonomous pass driven by a deep-repo audit. The agent
mapped backend↔frontend contracts, AI-pipeline integrity, state
machine completeness, dead routes, security/hygiene, reliability
gaps, and test coverage. This document is the consolidated record:
**every finding, every fix, every gap I deliberately left**.

## TL;DR

- **17 issues fixed**, all changes verified by re-running the full test
  suite (gateway + registry unit, 5 E2E flows including the new
  mukhtar-attestation contract test).
- **One demo-blocking bug killed**: the SPA was silently dropping the
  three-part attestation payload, so every mukhtar approve attempt
  returned 400. Passport approvals were uniformly broken.
- **All four service types** (id_new, id_renewal, passport_new,
  passport_renewal) now reach their expected terminal states from the
  seeder and from CI E2E tests.
- **Stack inventory rebuilt** for prod: `gateway_cron` sidecar runs the
  email-outbox + mukhtar-SLA sweepers on real schedules.

## What was actually wrong vs. what the audit reported

Audit produced 30 findings. Verified each before fixing — agents
hallucinate. Calibration:

| Audit said | Reality |
|---|---|
| Risk breakdown not persisted (MEDIUM) | Already persisted at `orchestrator.py:697` and logged at `:732`. False positive. |
| LLM trace only on success (MEDIUM) | `ai_extractor.py` returns trace dict on every outcome (success, error, skipped_*); orchestrator at `:322` logs each. False positive. |
| Hardcoded secrets in `.env.dev` (CRITICAL) | `.env.dev` is `.gitignore`d — secrets never committed. Hypothetical, not actual. Updated `.env.example` to be a complete current template. |
| Mukhtar transfer endpoint missing | Exists at `mukhtar.py:469`. False positive. |
| Mukhtar attestation contract mismatch (CRITICAL) | **Real and demo-blocking.** Frontend wrapper destructured only `{decision, notes, rejection_reasons}`, dropping all three attestation booleans. Confirmed with grep before fix. |

Net real critical issues: 1 of 3 reported. Net real high+medium: ~11 of
22 reported. The audit's signal/noise was decent but the prioritization
was off — the demo-blocking attestation bug was buried at #2 while
"hardcoded secrets" was elevated to #3 despite never having shipped.

## What I fixed

Each entry: file:line, what changed, why.

### Demo-blocking — would have killed the live defense

1. **[services/web/src/shared/api/mukhtar.js:20](services/web/src/shared/api/mukhtar.js#L20)** — Mukhtar `decide` API wrapper now forwards the full body. Was destructuring 3 of 6 fields, silently dropping `residence_verified`, `photo_verified`, `presence_verified`, `failed_attestation_reason`. Backend rejected every approve with 400. Documented the regression class in a code comment so it can't quietly come back.

### AI pipeline integrity

2. **[services/gateway/app/services/orchestrator.py:481](services/gateway/app/services/orchestrator.py#L481)** — `face_similarity` no longer defaults to 0 when Rekognition couldn't extract a reference face. For `id_new` and `passport_new` (where the only photo is the civil-registry extract — Rekognition often fails to find a face on it), this previously charged the case 100% face-risk despite a clean liveness check. Now: if `similarity_score is None` and liveness passed, fall back to liveness confidence as the face signal.

3. **[services/gateway/app/services/orchestrator.py:782](services/gateway/app/services/orchestrator.py#L782)** — `manual_review` routing now writes a `manual_review_required` audit log instead of `pass`-ing silently. Auditors querying audit_logs can now distinguish "case parked for clerk review" from "worker crashed mid-pipeline".

4. **[services/gateway/app/services/orchestrator.py:770-778](services/gateway/app/services/orchestrator.py#L770-L778)** — `generate_passport_application` (PDF generator, touches disk) now wrapped in try/except. Disk-full / template-error no longer leaves the mukhtar with no form to review — failure is audit-logged and the case continues to mukhtar.

5. **[services/gateway/app/services/orchestrator.py:679-686](services/gateway/app/services/orchestrator.py#L679-L686)** — Reconciliation now appends mismatched field names to `case.retake_reasons` as a `_reconciliation` entry. Citizens bounced to need_info on data mismatch will see the field names ("Declared values don't match the documents for: full_name, date_of_birth"), not just generic "data integrity issue". Existing UI banner picks up the format unchanged.

6. **[services/gateway/app/services/orchestrator.py:701-715](services/gateway/app/services/orchestrator.py#L701-L715)** — Registry-degraded mode no longer feeds 0 confidence into the risk scorer. When the registry service is unreachable (`status == "error"`), the score is set to neutral 1.0 with a `registry_degraded_mode` audit entry. Without this, an infra outage produced a wave of auto-rejections indistinguishable from genuine "no match in registry".

7. **[services/gateway/app/services/reconciliation.py:75-100](services/gateway/app/services/reconciliation.py#L75-L100), [:240-247](services/gateway/app/services/reconciliation.py#L240-L247)** — Added `SKIP_RECONCILIATION_FIELDS` set covering citizen-typed metadata that has no document analog (`renewal_reason`, `passport_validity_years`, `marital_status`, `address`, `phone`, `religious_sect`, `municipality`, `passport_type`). These were being counted as `not_found_in_ocr`, dragging integrity_score below the manual-review threshold and pushing clean cases into `reject` band. **Caught only because the seeder reproduced it.**

### Reliability / ops

8. **[docker-compose.yml:80-115](docker-compose.yml#L80-L115)** — New `gateway_cron` sidecar service. Two background loops in one container: email-outbox sweep every 60s, mukhtar-SLA escalation every hour. Restart-policy `unless-stopped`. Fixes the silent-fail mode where queued status emails never delivered and overdue mukhtar cases sat forever past SLA. Verified live: first tick logged `enqueued 0 outbox deliveries`, `sweep summary: scanned=1 reassigned=0 escalated=0`, `pushgateway: 200`.

9. **[services/gateway/Dockerfile:14-17](services/gateway/Dockerfile#L14-L17)** — Sweeper scripts (`scripts/sweep_*.py`) now copied into the gateway image (`/app/scripts/`). Were missing from the image, so the new cron service couldn't import them.

10. **[services/gateway/app/main.py:55-78](services/gateway/app/main.py#L55-L78)** — CORS allow-list resolution logged on startup with WARNING when empty. Misconfigured prod env (typo, missing scheme) now surfaces in the first log line instead of producing a fully-working backend that the SPA can't talk to.

11. **[services/gateway/alembic/versions/c2e3f4a5b601_unique_appointment_slot.py](services/gateway/alembic/versions/c2e3f4a5b601_unique_appointment_slot.py)** — New migration adds a partial unique index on `biometric_appointments(centre_id, slot_start) WHERE status IN ('booked','rescheduled')`. Closes the race condition where two citizens could pass the application-level "slot taken?" check between SELECT and INSERT. Migration applied successfully (head = `c2e3f4a5b601`).

12. **[services/gateway/app/routers/appointments.py:185-195](services/gateway/app/routers/appointments.py#L185-L195)** — Booking commit now catches `IntegrityError` from the new unique constraint and returns clean 409 `"Slot already taken"` instead of a 500.

### Test coverage

13. **[evaluation/test_mukhtar_attestation_e2e.py](evaluation/test_mukhtar_attestation_e2e.py)** — New 200-line E2E test that locks down the attestation contract. Bypasses the AI pipeline (DB-injects a case at `pending_mukhtar`) so the test isn't coupled to risk-score thresholds. Asserts: 2/3 attestations returns 400 with field-naming detail, 3/3 returns 200, audit log records all three booleans. Wired into CI.

14. **[.github/workflows/ci.yml:170-171](.github/workflows/ci.yml#L170-L171)** — CI runs the new test alongside the four service-type E2Es.

### Hygiene

15. **[.env.example](.env.example)** — Regenerated from `.env.dev` with placeholder values. Was 30+ keys behind — a deployer following the old template couldn't bring up the stack. Now covers JWT, Stripe, AWS, OpenAI, S3, observability, CORS, rate limits, the lot.

16. **[services/web/src/apps/clerk/pages/AdminAuditLogs.jsx:7-32](services/web/src/apps/clerk/pages/AdminAuditLogs.jsx#L7-L32)** — Action-label dropdown now lists the new audit actions (`manual_review_required`, `form_generation_failed`, `registry_degraded_mode`, `mukhtar_decision`, `appointment_*`, `payment_succeeded`) plus existing ones that were missing labels. Bilingual.

17. **[scripts/seed_demo.py](scripts/seed_demo.py)** — Already covered all 4 service types from gap #2; verified all 4 land at correct statuses after the recon fix above. id_new → payment_pending, id_renewal → payment_pending, passport_new → pending_mukhtar, passport_renewal → pending_mukhtar. ✅

## Test results

```
Gateway unit:           73 passed in 0.34s
Registry unit:          21 passed in 0.34s
test_id_renewal_e2e:    PASS
test_id_new_e2e:        PASS
test_passport_renewal:  PASS
test_passport_new_e2e:  PASS
test_mukhtar_attestation_e2e:  PASS  (NEW)
test_auth_e2e:          PASS
test_admin_e2e:         PASS
test_cases_e2e:         PASS
test_payment_e2e:       PASS
test_security_e2e:      PASS
test_tier2_endpoints:   PASS=32 FAIL=0
```

Live-stack smoke: all 4 service types seeded end-to-end via
`scripts/seed_demo.py`, each landed at the expected status.
`/api/v1/admin/stats` returns correct breakdown by service +
status. `/api/v1/admin/cases` paginates correctly.

## What I deliberately did NOT touch

Per the user's instruction in `docs/future-work.md`, the following
were out of scope and stay deferred:

- **Langfuse / LLM ops layers 3-5** — datasets, prompt management,
  online eval. Tracking via metrics + audit-log traces is enough for
  the prototype.
- **Real-mode CI lane** — flaky against external APIs, costs money
  per run, better as a scheduled job post-submission.
- **K8s manifests** — exist but unproven on a real cluster. Demo will
  run on Docker Compose; k8s belongs in a v2 deploy.
- **Bias / fairness eval** — needs a labelled stratified dataset that
  doesn't exist yet.
- **Adversarial fixtures** — covered partially by unit tests; full
  E2E adversarial coverage is week-2 work.

Audit findings I judged not worth fixing in 2 hours:

- **Idempotency key scope (audit #10)** — current `idempotency.py`
  implementation looked correct on inspection (keys include user.id +
  route). The audit flagged it speculatively without confirming. Skip.
- **Admin CSV export DoS (audit #11)** — admin role only, behind
  RoleRoute. A malicious clerk would already have read access to
  every case. Real fix is RBAC tiers within admin, not pagination.
- **Path-traversal mitigation in document image serving (audit #24)** —
  audit explicitly noted current code is safe (paths from uuid).
  No-op.
- **Stripe webhook event-ID matching (audit #25)** — defense-in-depth.
  Signature verification + downstream ownership checks already
  prevent the attack vector. Low priority.
- **Audit-log retention policy (audit #21)** — important but takes a
  full-day design (partitioning vs archive vs hot/cold tiering). Not a
  defense blocker.
- **Email outbox direct-send fallback (audit #4)** — the actual code
  path always goes through outbox; the audit's "swallowed exception"
  was the **outbox enqueue exception**, which would only fire if
  Postgres is down — at which point email is the least of your
  problems.

## What's still genuinely missing (post-audit punch list)

These are things I noticed during the audit that aren't blockers but
are real gaps:

| Severity | Item | Why deferred |
|---|---|---|
| MEDIUM | OCR + Face unit tests can't run on host venv (missing pip deps) | CI runs them in containers; works there. Local dev just gets gateway + registry. |
| MEDIUM | No integration test for the `gateway_cron` sweeps actually firing | Cron sidecar is verified by docker logs; full test would need to fast-forward time. |
| LOW | `passport_validity_years` declared as int but stored as str downstream | Reconciliation skip means it doesn't break anything; cleaner would be enum coercion in schema. |
| LOW | Risk weights live in `risk.py` constants — no admin-time override | Audit log captures the snapshot per case, so changing weights doesn't retroactively affect old decisions. Intentional. |
| LOW | `gateway_cron` runs sweeps in a single container; no HA | One container is enough for this load. K8s CronJob is the v2 deploy. |

## State of the system right now

- **Stack:** all 22 containers up, healthy, gateway responding to
  `/health/ready` with all checks green.
- **Tests:** 5 E2E flows green, 94 unit tests pass.
- **Demo data:** all 4 seeded cases at expected statuses (verified via
  `/admin/stats`).
- **Cron sidecar:** running, both sweepers ticked successfully on
  startup, pushgateway acknowledged metrics.
- **Migrations:** head at `c2e3f4a5b601` (the new appointment unique
  index).
- **Working tree:** dirty — every change above is uncommitted so you
  can review the full diff before committing. No `git add`, no
  `git commit`, no destructive operations performed.

## Next steps

You're now at the point where deploying makes sense. The pre-deploy
checklist:

1. `git diff` to review every change above. (~30 min)
2. `git add -A && git commit -m "prod-readiness pass"`.
3. Push and verify CI is green on the new tests.
4. Provision the deployment target (per the deployment plan we
   discussed: $6 VPS, Caddy auto-TLS, single docker-compose stack).
5. Bake `VITE_API_URL=https://yourdomain` into the web image.
6. Update Stripe webhook URL in the dashboard, copy new signing
   secret into prod env.
7. Run `python -m scripts.seed_demo` against the live URL.
8. Walk through `docs/demo-runbook.md` end-to-end on the live URL.
