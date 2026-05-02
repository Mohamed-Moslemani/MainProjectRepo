# Demo runbook — final defense

Click-by-click for the live demo. Print this. Have it next to the
laptop. Each step lists what to click, what to *say while clicking*,
and a one-line fallback if it breaks.

## Pre-demo, T-30 min

```bash
# 1. Stack up (mock mode, so no Vision/Rekognition cost during demo)
sed -i 's/OCR_MOCK_MODE=false/OCR_MOCK_MODE=true/' .env.dev
sed -i 's/FACE_MOCK_MODE=false/FACE_MOCK_MODE=true/' .env.dev
docker compose --env-file .env.dev up -d --build

# 2. Wait for gateway readiness
until curl -sf http://localhost:8000/health/ready; do sleep 2; done

# 3. Reset and reseed
python -m scripts.reset_demo
python -m scripts.seed_demo

# 4. Stripe webhook listener (separate terminal, leave running)
stripe listen --forward-to localhost:8000/api/v1/payments/webhook

# 5. Open browsers / tabs:
#    Tab A: http://localhost:3000              (citizen, log in as demo_citizen@docflow.example.com)
#    Tab B: http://localhost:3000/admin        (clerk, log in as demo_admin@docflow.example.com)
#    Tab C: http://localhost:3000/mukhtar      (mukhtar, log in as demo_mukhtar@docflow.example.com)
#    Tab D: http://localhost:3001              (Grafana → AI Observability dashboard)
```

Demo password for all three accounts: `Demo!Pass#1`

If the seeder fails: run `python -m scripts.reset_demo` once and
retry. If that fails too, fall back to the backup video.

## Walkthrough — 8 minutes total

### 1. The problem (60s, no clicking)

Say: *"Today, renewing a Lebanese ID or passport means three trips
to a GDGS office, paper forms, and unpredictable wait times.
DocFlow lets the citizen do everything except biometric capture
online — upload, validate, pay, track. The one in-person visit is
just for fingerprints and pickup."*

### 2. Citizen submission flow (Tab A) — 90s

- Click **New application → Passport renewal**
- Upload `evaluation/real_samples/haddad_sarah/passport_bio.jpg`
  as the data page (works because mock mode returns a clean fixture
  regardless, but the user file makes it look real)
- Upload any image as civil-registry extract
- **Don't actually run liveness** — the seeder pre-built a similar
  case. Click into the **already-seeded passport_renewal case
  (status: pending_mukhtar)** in the citizen tracking view.

Say while clicking: *"Behind the scenes the gateway just dispatched
to a worker that runs OCR, MRZ parse, face match, civil-registry
verification, reconciliation, and risk scoring. Each one is in the
audit log."*

**Fallback:** if upload UI hangs, switch to the seeded case.

### 3. Audit trail — what the AI did (Tab B, 90s)

- **Admin → Audit Logs**
- Filter: paste the case_id from the seeder output
- Show entries in this order:
  1. `ocr_completed` (per document) — show extracted_fields,
     confidence_scores, MRZ
  2. `llm_extraction_completed` — *"This is the LLM extractor.
     We use gpt-4o-mini for civil-registry extracts because they're
     three-column tables that break regex. Every call is logged
     with the prompt, response, tokens, and cost so the decision is
     auditable."*
  3. `reconciliation_completed` — show integrity_score, mismatch_flags
  4. `face_verification_completed` — show similarity, liveness_passed
  5. `registry_verification_completed`
  6. `case_status_updated` to `pending_mukhtar`

Say: *"Every AI signal that contributed to the decision is here.
A reviewer six months from now can replay the exact decision."*

### 4. Mukhtar approval (Tab C, 60s)

- Mukhtar inbox shows the pending case
- Click into it → **Approve with stamp**
- Show the case status flips to `approved → payment_pending`

### 5. Payment + production (Tab A, 60s)

- Switch to citizen tab, second seeded case (id_renewal at
  payment_pending)
- Click **Pay** → Stripe checkout → use card `4242 4242 4242 4242`,
  any expiry/CVC
- After redirect, show case at `in_production`

Say: *"Stripe webhook just landed — gateway flipped the case state.
The citizen now has a tracking page that updates as the GDGS centre
moves it through production and ready-for-pickup."*

**Fallback:** if Stripe checkout doesn't redirect, paste a curl
that hits `/api/v1/payments/webhook` with a synthetic event.
*Better fallback:* the backup video already has this flow.

### 6. AI observability (Tab D, 60s)

- Grafana → **DocFlow — AI Observability** dashboard
- Walk through the rows top to bottom:
  - **OCR**: request count, retake rate, MRZ outcomes, avg confidence
  - **LLM Extractor**: total calls, success rate, token usage, *est. USD cost*
  - **Face**: pass rate, similarity distribution, liveness outcomes
  - **Civil Registry**: match rate, confidence distribution
  - **Reconciliation**: integrity score, validation outcomes, top mismatched fields
  - **Risk & Pipeline**: risk score p50/p95, decision routing, pipeline duration

Say: *"Every AI signal has aggregate observability — call count,
latency, success rate, token cost. Per-case audit lives in the
audit log we just looked at. Together that's metrics + traces, the
two layers of LLM ops you need before adding prompt management."*

### 7. Closing (60s, no clicking)

Hit on:

- **Reproducibility**: every decision is replayable from audit log
  + image hash + model versions
- **Conservative routing**: borderline → manual_review, not auto-deny
- **Lebanese-specific rules**: pre-2016 passports correctly redirect
  to in-person flow; minors require guardian consent
- **What's next**: real-docs eval ran 2026-04-28, 21/29 fields
  matched on positive cases (see `docs/real-docs-eval-2026-04-28.md`)

## Recovery moves if the live demo breaks

| Symptom | Move |
| --- | --- |
| Gateway returns 5xx during click | switch to backup video, keep talking |
| Stripe webhook didn't fire | `stripe trigger checkout.session.completed --override checkout_session:metadata.case_id=<id>` |
| Pipeline stuck at submitted | `docker compose logs gateway_worker --tail=50` (it's the Arq worker, restart if dead) |
| Mock OCR returning wrong text | `docker compose restart ocr` — usually a stale container after a code change |
| Audit log filter empty | API expects `action=llm_extraction_completed`; copy/paste from this runbook |

## Backup video

Recorded version of the entire walkthrough at
`docs/demo-backup.mp4` (record this T-1 day, after a clean dry-run).

## Don't say

- *"It's just a prototype"* — it's a final-year project, defend it
- *"This part doesn't work"* — if asked about a known limit
  (diplomatic passports, non-Lebanese MRZ), point at the eval doc
  and frame it as a documented future-work item
- *"I didn't have time to..."* — frame as scope decisions, e.g.
  "Langfuse and adversarial fixtures are the natural next layer
  but were out of scope for the core prototype"
