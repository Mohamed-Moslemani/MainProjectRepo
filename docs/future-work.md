# Future work

Items deliberately out of scope for the v1 prototype, with rationale
for why they were deferred and what each one unlocks. Ordered roughly
by what to do first if work resumes after submission.

## LLM ops maturity ladder

DocFlow currently sits at **layer 2** of the standard LLM-ops ladder.
The remaining layers are well-understood industry practice; each
gives a specific capability the prototype intentionally does without.

| Layer | Capability | Status |
| ----- | ---------- | ------ |
| 1. **Metrics** — aggregate observability | call count, success rate, latency, tokens, cost | ✅ shipped (Prometheus + Grafana, `06-ai-observability.json`) |
| 2. **Traces** — per-call replay | prompt, response, tokens, model captured per case | ✅ shipped (`audit_logs.action='llm_extraction_completed'`) |
| 3. **Evaluation datasets** — quality drift detection | pinned input set, scored outputs, drift over model versions | ⏳ partial — one-off run captured in `docs/real-docs-eval-2026-04-28.md`, no scheduled re-runs |
| 4. **Prompt management** — versioned, hot-swappable prompts | non-engineers tweak prompts without redeploy, A/B testing | ⏳ deferred — would be Langfuse-managed |
| 5. **Online evaluation** — LLM-as-judge in prod | every prod call scored on a quality rubric, alerts on regressions | ⏳ deferred |

**Why deferred:** the prototype has a single LLM prompt
(civil-registry extract) used in a single place. Layers 3-5 are
valuable when you have 5+ prompts and a non-engineer iterating on
them — neither was true here. Adding Langfuse for one prompt would
have been infrastructure cost without a corresponding capability win,
and would have compromised the demo-readiness deadline.

**What it unlocks if added:** Layer 3 catches the case where a model
upgrade silently regresses on Lebanese script (extracts `محمد` as
`محمج` because of a tokenizer change). Layer 4 lets the GDGS team
update field-extraction instructions without a code deploy. Layer 5
catches drift between offline eval and prod traffic distribution.

## Adversarial / failure-path fixtures

Mock-mode E2E currently exercises only the happy path. Production
identity systems also have fixtures for: blurry image, glare, wrong
document type, mismatched name, expired passport, MRZ checksum
failure, low face similarity, liveness spoof. Each is a separate
fixture asserting the pipeline routes to the *correct* failure
state.

**Why deferred:** unit tests cover most of these in isolation
(`test_mrz_parser.py`, `test_quality.py`, etc.). Wiring them into
full E2E with assertions on routing was not on the critical path
for a demoable prototype.

**What it unlocks:** confidence that the orchestrator's gate logic
is correct under failure, not just under success. Currently we know
each gate fires correctly; we don't have automated proof that they
*compose* correctly when multiple gates fail together.

## Bias / fairness evaluation

No FRVT-style bias analysis on the face matching (performance across
skin tones, ages, genders) and no fairness analysis on the LLM
extractor (does it perform differently on Christian vs. Muslim
Lebanese surnames?).

**Why deferred:** requires a labelled dataset stratified by
demographic attribute, which is non-trivial to assemble and
politically sensitive to publish. Out of scope for a 16-day final
project.

**What it unlocks:** required reading for any GDGS procurement
process. A NIST FRVT-style report on the face component would be
the strongest external validation for production deployment.

## Real-mode CI lane

CI proves correctness in mock mode (Vision + Rekognition stubbed).
A separate gated CI lane that runs on merge-to-main, hitting real
GCV and AWS Rekognition with one or two known images, would catch
upstream API regressions.

**Why deferred:** ~$0.02 per run is fine, but the dependency on
external API availability makes the lane flakier than a trunk-blocking
test deserves to be. Better implemented as a scheduled (cron) run
that posts a summary to the team channel rather than blocking
merges.

**What it unlocks:** detection of "Vision changed their JSON shape"
or "Rekognition rotated their similarity-score scale" before it hits
prod — the most common silent-AI-regression failure mode.

## Caching for LLM calls

Each civil-registry extract makes a fresh LLM call. Identical
re-submits (same image, same hash) pay full cost again.

**Why deferred:** the `input_hash` field already exists on
`OCRResult`. A cache keyed on `(input_hash, document_type, model,
prompt_version)` would be one DB lookup before each LLM call. ~1 hour
to add, but no operational pain in the prototype since traffic is
zero. Adds a bounded amount of complexity (cache invalidation on
prompt edit) for a real cost saving only at scale.

## Data residency / on-prem

Lebanese government identity data going to Google Cloud (OCR) and
AWS (face) is a procurement blocker. A v2 deployment would replace:

- Google Vision → Tesseract or PaddleOCR running locally
- AWS Rekognition → InsightFace or DeepFace, self-hosted
- gpt-4o-mini → Llama 3 / Qwen-VL on-prem

**Why deferred:** the prototype's value proposition is the
*pipeline orchestration*, not the model choice. Each component is
isolated behind an HTTP boundary (`call_ocr_service`,
`call_face_service`) — swapping providers is a configuration
change, not a refactor.

**What it unlocks:** the only path to a real GDGS production
deployment. Cloud providers are not an option for this dataset.

## K8s production hardening

K8s manifests exist (`k8s/base/` with kustomize) covering autoscale,
disruption budgets, network policies, and ingress, but have not
been deployed to a real cluster end-to-end. The demo runs on
Docker Compose.

**Why deferred:** a real cluster takes a day to debug under the
best of circumstances. The Compose deployment proves the same code
works in containers; the kustomize manifests prove the production
shape was thought through. Deferring the full cluster deployment
to post-submission is the lower-risk move.

**What it unlocks:** horizontal scaling, zero-downtime deploys,
proper secret management via SealedSecrets / Vault.
