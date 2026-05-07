# DocFlow Lebanon

> **Repository:** [github.com/Mohamed-Moslemani/MainProjectRepo](https://github.com/Mohamed-Moslemani/MainProjectRepo)
>
> **234 commits** across **7 branches** (`main`, `develop`, `monorepo`, `mohamedmoslemani/gatewayServices`, `mohamedmoslemani/services/faceService`, `mohamedmoslemani/webapp`, and more). All work by a single contributor over the course of the project.

DocFlow is a microservice-based document workflow platform that digitizes the process of applying for Lebanese identity documents (national IDs and passports). Citizens upload documents online, the system runs AI-powered validation (OCR, face verification, civil-registry checks, risk scoring), routes cases through a mukhtar attestation step, collects payment via Stripe, and tracks the application through production to pickup. The only in-person visit required is for biometric capture.

The platform serves three user roles through a single React SPA: **citizens** who submit and track applications, **mukhtars** who attest to identity and residence, and **clerks/admins** who review edge cases, manage appointment queues, and monitor system health.

## Table of contents

- [Technology overview](#technology-overview)
- [Repository structure](#repository-structure)
- [Architecture](#architecture)
  - [Service topology](#service-topology)
  - [Gateway (API orchestrator)](#gateway-api-orchestrator)
  - [OCR service](#ocr-service)
  - [Face service](#face-service)
  - [Registry service](#registry-service)
  - [Web frontend](#web-frontend)
  - [Background workers and cron](#background-workers-and-cron)
  - [Inter-service communication](#inter-service-communication)
  - [Data stores](#data-stores)
  - [Case lifecycle](#case-lifecycle)
  - [Shared Python module](#shared-python-module)
- [Cloud deployment vs. on-premises](#cloud-deployment-vs-on-premises)
  - [Single-VM deployment (Docker Compose)](#single-vm-deployment-docker-compose)
  - [Cloud-managed services overlay](#cloud-managed-services-overlay)
  - [Kubernetes deployment](#kubernetes-deployment)
  - [Data residency and on-prem path](#data-residency-and-on-prem-path)
- [Observability](#observability)
- [CI/CD pipelines](#cicd-pipelines)
- [Testing](#testing)
- [Getting started](#getting-started)
- [Environment variables](#environment-variables)
- [Documentation index](#documentation-index)

## Technology overview

| Layer | Stack |
|-------|-------|
| Backend services | Python 3.13, FastAPI, Uvicorn, SQLAlchemy 2 (async), Alembic |
| Frontend | React 19, Vite 8, React Router, axios, i18next (Arabic/English), AWS Amplify UI (liveness) |
| Databases | PostgreSQL 16 (gateway DB + registry DB), Redis 7 (rate limits, job queue) |
| Object storage | MinIO (dev), Cloudflare R2 or AWS S3 (prod) |
| AI / ML providers | Google Cloud Vision (OCR), OpenAI gpt-4o (LLM table extraction), AWS Rekognition (face match + liveness) |
| Payments | Stripe Checkout + webhooks |
| Observability | Prometheus, Grafana (10 dashboards), Alertmanager, Jaeger (OTLP), GlitchTip/Sentry, Langfuse (LLM tracing) |
| Deployment | Docker Compose, Kustomize (Kubernetes), GitHub Actions (CI + CD) |

## Repository structure

This is a polyglot monorepo. All services, infrastructure manifests, tests, and tooling live in a single repository without a formal workspace manager (no npm workspaces, no Lerna, no Nx). Python services manage dependencies through per-service `requirements.txt` files. The frontend is a single Vite project.

```
.
├── services/
│   ├── gateway/        FastAPI API gateway + orchestrator (Python)
│   ├── ocr/            OCR microservice (Python)
│   ├── face/           Face verification microservice (Python)
│   ├── registry/       Simulated civil registry (Python)
│   └── web/            React SPA (citizen, clerk, mukhtar portals)
├── shared/             Shared Python package (schemas, telemetry, config, request ID)
├── k8s/
│   ├── base/           Kustomize base manifests (full stack, cluster-agnostic)
│   └── overlays/
│       ├── dev/        Local kind/k3d, mock AI, no TLS
│       └── prod/       Real cluster, Let's Encrypt TLS, Postgres HA
├── monitoring/
│   ├── prometheus/     Scrape config, alert rules, recording rules, drift alerts
│   ├── grafana/        10 JSON dashboards + provisioning
│   ├── alertmanager/   Routing config + secrets
│   └── alloy/          Grafana Alloy config (cloud metrics/logs shipping)
├── nginx/              Edge reverse proxy configs (dev + cloud)
├── evaluation/         E2E integration tests and real-document evaluation samples
├── load/               Locust load tests with SLO enforcement
├── scripts/            Operational helpers (seeder, demo reset, sweepers, Grafana Cloud import)
├── docs/               Runbooks, evaluation results, prod-readiness audit, future work
├── .github/workflows/  CI, deploy, security scanning, load testing
├── docker-compose.yml          Full local stack (22+ containers)
├── docker-compose.cloud.yml    Cloud overlay (managed observability + storage)
├── .env.example                Environment template (local dev)
└── .env.cloud.example          Environment template (cloud mode)
```

Each backend service has its own `Dockerfile`, `requirements.txt`, `app/` package with a FastAPI entry point, and a `tests/` directory. The gateway and registry services additionally have `alembic/` directories for database migrations.

## Architecture

### Service topology

The system follows a **gateway-orchestrated microservice** pattern. A single public-facing API gateway receives all client requests and delegates AI workloads to internal services over HTTP. The internal services (OCR, face, registry) are never exposed to the public internet.

```
                    ┌─────────────┐
  Browser ─────────►│    nginx    │
                    │ (TLS term.) │
                    └──────┬──────┘
                           │
              ┌────────────┴───────────────┐
              │                            │
              ▼                            ▼
        ┌──────────┐               ┌──────────────┐
        │ Gateway  │               │     Web      │
        │ (FastAPI)│               │ (React SPA)  │
        └────┬─────┘               └──────────────┘
             │
    ┌────────┼─────────┐
    │        │         │
    ▼        ▼         ▼
┌───────┐ ┌──────┐ ┌──────────┐
│  OCR  │ │ Face │ │ Registry │
│:8001  │ │:8002 │ │:8003     │
└───────┘ └──────┘ └──────────┘
```

**nginx** terminates TLS and routes traffic: `/api/*`, `/health`, `/docs`, `/openapi.json`, and `/redoc` go to the gateway; everything else goes to the web SPA. The Kubernetes ingress mirrors this exact split.

### Gateway (API orchestrator)

The gateway (`services/gateway/`) is the central coordination point. It runs on FastAPI and exposes the full public REST API:

| Prefix | Responsibility |
|--------|----------------|
| `/api/v1/auth` | Registration, login, JWT refresh, password reset, email verification |
| `/api/v1/cases` | Case CRUD, document uploads, submission, tracking |
| `/api/v1/payments` | Stripe Checkout session creation, webhook receiver |
| `/api/v1/admin` | Clerk review queue, audit logs, stats, user management |
| `/api/v1/mukhtar` | Mukhtar case queue, attestation decisions, transfers |
| `/api/v1/appointments` | Biometric appointment booking (citizen + clerk confirmation) |
| `/api/v1/liveness` | AWS Amplify liveness proxy (browser-to-gateway credential relay) |
| `/api/v1/reference` | Public lookup data (sects, centres, passport validity options) |
| `/api/v1/sentry-tunnel` | Same-origin forwarder for Sentry browser error reports |
| `/health`, `/health/ready` | Liveness and readiness probes |
| `/metrics` | Prometheus-format metrics (via `prometheus-fastapi-instrumentator`) |

When a citizen submits a case, the gateway enqueues a job on the **Arq** queue (backed by Redis). The `gateway_worker` process picks it up and runs the **orchestration pipeline**: OCR on each document, MRZ parsing, face verification, civil-registry lookup, field reconciliation between declared and extracted data, and risk scoring. Each step produces an audit log entry, making every AI decision replayable after the fact.

**Authentication** uses JWT access + refresh tokens with bcrypt password hashing. Role-based access control is enforced via a `require_role()` dependency that gates endpoints to `citizen`, `mukhtar`, `clerk`, or `admin`. Rate limiting (per-IP and per-email) is implemented through Redis counters.

### OCR service

The OCR service (`services/ocr/`) processes document images. It runs Google Cloud Vision for text extraction and an OpenAI gpt-4o fallback for table-shaped documents (civil-registry extracts that break regex-based parsing). The service includes:

- Image quality assessment (blur, glare, angle, resolution)
- MRZ (Machine Readable Zone) parsing for passport pages
- Confidence scoring per extracted field
- A full **mock mode** (`OCR_MOCK_MODE=true`) that returns deterministic fixtures without calling any external API, used in CI and demo environments
- Langfuse integration for LLM prompt tracing and cost tracking

Single endpoint: `POST /api/v1/ocr/process`.

### Face service

The face service (`services/face/`) handles identity verification through:

- **Face matching** via AWS Rekognition (compares a selfie against a reference document photo)
- **Liveness detection** via the AWS Amplify liveness flow (browser captures a short video sequence, results are verified server-side)
- A full **mock mode** (`FACE_MOCK_MODE=true`) for testing without AWS calls

Endpoints: `POST /api/v1/face/verify`, plus the liveness sub-router at `/api/v1/face/liveness` (credentials, session creation, result retrieval).

### Registry service

The registry service (`services/registry/`) simulates the Lebanese Ministry of Interior civil registry. It runs its own PostgreSQL database, seeded with citizen records from `services/registry/seed/citizens.json`. The gateway calls it during the orchestration pipeline to cross-reference declared identity data against the "official" record.

Single endpoint: `POST /api/v1/registry/verify`.

In a real deployment, this service would be replaced by an integration with the actual GDGS registry API. The HTTP boundary (`call_registry_service`) makes swapping trivial: point `GATEWAY_REGISTRY_SERVICE_URL` at the real endpoint.

### Web frontend

The frontend (`services/web/`) is a single React 19 SPA built with Vite 8 that serves three portals from one codebase:

```
src/
├── apps/
│   ├── citizen/     Dashboard, case detail, document upload, booking, tracking
│   ├── clerk/       Admin dashboard, review queue, audit logs, case management
│   └── mukhtar/     Mukhtar inbox, attestation decisions, case transfers
└── shared/          Auth context, axios client, components, i18n, styles
```

The three portals share a single auth token, a single design system, and a common component library. Path aliases (`@shared/*`, `@citizen/*`, `@clerk/*`, `@mukhtar/*`) enforce clean imports. A deliberate dependency rule keeps role-specific code isolated: `apps/<role>` can import from `@shared` but not from another role's `apps/` folder.

The SPA supports Arabic and English via i18next and uses the AWS Amplify UI liveness component for the browser-side biometric capture flow.

### Background workers and cron

The gateway codebase runs in three modes from the same Docker image:

| Container | Command | Purpose |
|-----------|---------|---------|
| `gateway` | `uvicorn app.main:app` | HTTP API server |
| `gateway_worker` | `arq app.queue.WorkerSettings` | Async job consumer (orchestration pipeline, email delivery). Horizontally scalable with `--scale gateway_worker=N`. |
| `gateway_cron` | Shell loop running two Python scripts | Email outbox sweep (every 60s) and mukhtar SLA escalation (every hour). Without the cron sweeper, queued status emails never deliver and overdue mukhtar cases sit past SLA indefinitely. |

### Inter-service communication

| Mechanism | Where | Details |
|-----------|-------|---------|
| **Synchronous HTTP (REST/JSON)** | Gateway to OCR, Face, Registry | `httpx.AsyncClient` in `services/gateway/app/services/orchestrator.py`. Internal URLs are configured via `GATEWAY_OCR_SERVICE_URL`, `GATEWAY_FACE_SERVICE_URL`. |
| **Arq job queue (Redis-backed)** | Gateway to Gateway Worker | Durable async jobs for the orchestration pipeline, email outbox delivery. |
| **Stripe webhooks** | Stripe to Gateway | `POST /api/v1/payments/webhook` receives checkout completion and payment failure events. |

There is no service mesh. Services communicate directly over the Docker/Kubernetes internal network. Kubernetes NetworkPolicies restrict which pods can talk to each other.

### Data stores

| Store | Used by | Purpose |
|-------|---------|---------|
| **PostgreSQL** (`docflow` database) | Gateway | Cases, users, documents, audit logs, appointments, payments, email outbox. Managed via SQLAlchemy 2 async + Alembic migrations. |
| **PostgreSQL** (`registry` database) | Registry service | Simulated civil-registry citizen records. Separate database so schema changes in either service are independent. |
| **Redis** | Gateway, Gateway Worker, Gateway Cron | Rate limiting (db 0), Arq job queue (db 0). GlitchTip uses db 1 when running self-hosted. |
| **S3-compatible object storage** | Gateway, OCR | Uploaded document images. MinIO in local dev; Cloudflare R2 or AWS S3 in production. Accessed via `aioboto3`. |

### Case lifecycle

A case moves through a state machine defined in `shared/schemas.py`:

```
draft
  → submitted
    → validated
      → risk_evaluated
        ├── need_info          (missing or unclear documents)
        ├── pending_mukhtar    (passport flows: mukhtar attestation required)
        ├── approved
        │   → payment_pending
        │     ├── payment_failed (retry allowed)
        │     └── biometric_appointment_required (first-time passports)
        │       → in_production
        │         → ready_for_pickup
        │           → closed
        └── rejected
```

Each transition writes an audit log entry. The orchestration pipeline after `submitted` runs: document OCR, MRZ parse, face verification, liveness check, civil-registry cross-reference, field reconciliation, and risk scoring. Cases with borderline risk scores route to `manual_review` (clerk queue) rather than auto-rejecting.

### Shared Python module

The `shared/` package is mounted into every Python service container. It contains:

| File | Purpose |
|------|---------|
| `schemas.py` | Cross-service Pydantic models and enums (`ServiceType`, `CaseStatus`, `DocumentType`, `UserRole`, etc.) |
| `telemetry.py` | OpenTelemetry setup (OTLP gRPC/HTTP export to Jaeger or Grafana Cloud Tempo) |
| `request_id.py` | `RequestIDMiddleware` and logging filter for request correlation across services |
| `config.py` | Environment variable loading helpers |
| `model_info.py` | Shared model metadata |

## Cloud deployment vs. on-premises

DocFlow supports three deployment models, from lightest to most production-ready:

### Single-VM deployment (Docker Compose)

The default and simplest path. A single `docker compose up -d` brings up the full stack: application services, databases, object storage (MinIO), and a complete self-hosted observability stack (Prometheus, Grafana, Alertmanager, Jaeger, GlitchTip).

```bash
cp .env.example .env.dev
# Edit .env.dev with real credentials
docker compose --env-file .env.dev up -d
```

This runs 22+ containers on a single machine. The GitHub Actions `deploy.yml` workflow automates this: it SSHs to a configured VM, pulls the latest code, and runs `docker compose up -d --build`.

**Suitable for:** demos, development, single-server staging, low-traffic deployments.

### Cloud-managed services overlay

For production on a single VM but with cloud-grade reliability for observability and storage, the `docker-compose.cloud.yml` overlay replaces self-hosted components with managed services:

| Self-hosted component | Replaced by |
|----------------------|-------------|
| Prometheus, Grafana, Alertmanager, Jaeger, Pushgateway | **Grafana Cloud** (metrics via Alloy remote_write, traces via OTLP, logs via Loki) |
| GlitchTip (error tracking) | **Sentry** |
| MinIO (object storage) | **Cloudflare R2** (S3-compatible, zero egress cost) |
| PostgreSQL (optional) | **Neon** serverless Postgres (commented out by default) |

```bash
cp .env.cloud.example .env.cloud
# Fill in Grafana Cloud, Sentry, R2 credentials
docker compose --env-file .env.cloud \
  -f docker-compose.yml -f docker-compose.cloud.yml up -d
```

The overlay uses Docker Compose profiles to disable replaced services and adds a **Grafana Alloy** container that scrapes local `/metrics` endpoints and ships them to Grafana Cloud. This reduces the container count from 22+ down to around 12 while retaining the same application topology.

The cloud services used all have meaningful free tiers: Grafana Cloud (10k series, 50 GB logs, 50 GB traces), Sentry (5k errors/month), Cloudflare R2 (10 GB storage, zero egress), Neon (0.5 GB, 190 compute-hours/month).

**Suitable for:** production on a VPS or droplet (e.g., DigitalOcean, Hetzner) with cloud-backed reliability.

### Kubernetes deployment

For horizontal scaling and zero-downtime rollouts, the `k8s/` directory contains a Kustomize-based manifest set:

```
k8s/
├── base/                Cluster-agnostic: deployments, services, ingress, PVC, HPA, PDB, network policies
├── overlays/
│   ├── dev/             Mock AI on, no TLS, localhost ingress, local images
│   └── prod/            Real domain, Let's Encrypt via cert-manager, CNPG Postgres HA
└── operators/
    └── cnpg/            CloudNativePG operator usage notes
```

The base manifests deploy: gateway, gateway-worker, ocr, face, registry, web, PostgreSQL (StatefulSet), Redis (StatefulSet), registry-postgres, and an nginx-ingress with cert-manager for automatic TLS. The prod overlay adds **CloudNativePG** for Postgres high availability with automated failover and backups to S3-compatible storage.

Tested against single-node **k3s** on Hetzner VPS, but the manifests are standard Kubernetes and work on any cluster with an nginx-ingress controller and cert-manager.

The CI pipeline (`deploy.yml`) can deploy to Kubernetes: it builds and pushes images to GHCR, pins them by SHA in the Kustomize overlay, substitutes the domain, and runs `kubectl apply`. This path activates when the `DOCFLOW_DOMAIN` GitHub Actions variable is set.

**Suitable for:** production deployments that need horizontal scaling, pod disruption budgets, autoscaling, and network policy enforcement.

### Data residency and on-prem path

For government deployment, Lebanese citizen identity data flowing to US-based cloud providers (Google Cloud for OCR, AWS for face verification, OpenAI for LLM extraction) is a procurement blocker. The architecture is designed for provider swapability: each AI component is isolated behind an HTTP boundary in its own service. The on-prem replacement path is:

| Current provider | On-prem replacement | Change required |
|-----------------|---------------------|-----------------|
| Google Cloud Vision | Tesseract or PaddleOCR (self-hosted) | Implement alternative in `services/ocr/` |
| AWS Rekognition | InsightFace or DeepFace (self-hosted) | Implement alternative in `services/face/` |
| OpenAI gpt-4o | Llama 3 or Qwen-VL (local GPU) | Change `OCR_LLM_PROVIDER` config |

The gateway never calls AI providers directly. It calls `http://ocr:8001/api/v1/ocr/process` and `http://face:8002/api/v1/face/verify`. Swapping the provider is a change inside the service container, not a refactor of the orchestration layer.

## Observability

The system ships with a full observability stack configured out of the box:

**Metrics:** Prometheus scrapes `/metrics` from every FastAPI service (via `prometheus-fastapi-instrumentator`), plus dedicated exporters for PostgreSQL and Redis. Recording rules pre-compute aggregates. Alert rules cover service health, error rates, latency budgets, and AI pipeline drift.

**Dashboards:** 10 pre-provisioned Grafana dashboards:

1. Service Health (golden signals per service)
2. Gateway API (endpoint-level latency, error rates, throughput)
3. PostgreSQL (connections, query performance, replication lag)
4. Redis (memory, connected clients, command rates)
5. Infrastructure (container CPU, memory, network)
6. AI Observability (OCR call count, retake rate, MRZ outcomes, LLM token cost)
7. Face Verification (pass rate, similarity distribution, liveness outcomes)
8. Civil Registry (match rate, confidence distribution)
9. Reconciliation (integrity scores, validation outcomes, top mismatched fields)
10. Anti-Spoof (drift detection across AI signals)

**Tracing:** OpenTelemetry auto-instrumentation exports spans via OTLP gRPC to Jaeger (local) or Grafana Cloud Tempo (cloud). Every HTTP request carries a correlation ID (`X-Request-ID`) through all services.

**Error tracking:** GlitchTip (self-hosted Sentry-compatible) in local mode; Sentry SaaS in cloud mode. Frontend errors are tunneled through the gateway (`/api/v1/sentry-tunnel`) to avoid ad-blocker interference.

**LLM observability:** Langfuse traces every LLM call with prompt, response, token count, model version, and estimated cost. Stored per-case in the audit log for post-hoc decision replay.

## CI/CD pipelines

All pipelines run on GitHub Actions (`.github/workflows/`):

| Workflow | Trigger | What it does |
|----------|---------|--------------|
| `ci.yml` | Push, PR | ESLint (web), pytest unit tests (gateway, ocr, face), Docker build matrix (no push), E2E tests via Docker Compose with mock AI |
| `deploy.yml` | Push to main/develop | Builds + pushes 5 images to GHCR, cosign signing, SBOM generation (Syft), Trivy vulnerability scan. Deploys via kubectl/kustomize (when `DOCFLOW_DOMAIN` is set) or via SSH + Docker Compose (when `DEPLOY_VM_ENABLED` is true). |
| `security.yml` | Push, PR | Trivy filesystem scan, Gitleaks (secret detection), Bandit (Python static analysis), kube-linter (Kubernetes manifest linting) |
| `load-test.yml` | Nightly, manual | Locust baseline (50 users, 5/s spawn, 2-minute window) with p95 latency SLO enforcement per endpoint |

## Testing

| Layer | Location | Details |
|-------|----------|---------|
| Unit tests | `services/gateway/tests/`, `services/ocr/tests/`, `services/face/tests/`, `services/registry/tests/` | pytest, 94+ tests across all services |
| E2E integration | `evaluation/test_*_e2e.py` | Full pipeline tests per service type (id_new, id_renewal, passport_new, passport_renewal), plus auth, admin, cases, payment, security, mukhtar attestation, and tier-2 endpoint coverage |
| Load tests | `load/locustfile.py` | p95 latency budgets: login 800ms, case list 250ms, case create 500ms, health 50ms, admin queue 400ms. 1% error rate budget. |
| Real-document evaluation | `evaluation/real_samples/` | Evaluation against actual Lebanese documents (results documented in `docs/real-docs-eval-2026-04-28.md`) |

## Getting started

### Prerequisites

- Docker and Docker Compose v2
- Python 3.13+ (for running scripts outside containers)
- Node.js 20+ (only if developing the frontend outside Docker)

### Local development

```bash
# 1. Clone and configure environment
git clone https://github.com/Mohamed-Moslemani/MainProjectRepo.git && cd MainProjectRepo
cp .env.example .env.dev
# Edit .env.dev: at minimum, set GATEWAY_JWT_SECRET (run `openssl rand -hex 32`)

# 2. Start the full stack in mock mode (no external API calls)
OCR_MOCK_MODE=true FACE_MOCK_MODE=true docker compose --env-file .env.dev up -d --build

# 3. Wait for readiness
# Linux/macOS:
until curl -sf http://localhost:8000/health/ready; do sleep 2; done
# PowerShell:
while (-not (Invoke-WebRequest http://localhost:8000/health/ready -UseBasicParsing -ErrorAction SilentlyContinue)) { Start-Sleep 2 }

# 4. Seed demo data
python -m scripts.seed_demo

# 5. Open the app
# Citizen portal:  http://localhost:3000
# Admin portal:    http://localhost:3000/admin
# Mukhtar portal:  http://localhost:3000/mukhtar
# Grafana:         http://localhost:3001 (admin/docflow)
# Jaeger:          http://localhost:16686
# MinIO console:   http://localhost:9001
```

### Running tests

```bash
# Unit tests (inside containers)
docker compose exec gateway pytest tests/ -v
docker compose exec registry pytest tests/ -v

# E2E tests (requires running stack in mock mode)
python -m evaluation.run_all_tests
```

## Environment variables

Full templates with documentation are provided in:

- **`.env.example`** for local development (JWT, Stripe, AWS, OpenAI, S3, SMTP, CORS, rate limits, observability, mock mode toggles)
- **`.env.cloud.example`** for cloud mode (Grafana Cloud, Sentry, Cloudflare R2, Neon, OTLP endpoints)

Key configuration groups:

| Group | Variables | Notes |
|-------|-----------|-------|
| Auth | `GATEWAY_JWT_SECRET`, `GATEWAY_JWT_ALGORITHM`, `GATEWAY_JWT_EXPIRY_MINUTES` | Generate secret with `openssl rand -hex 32` |
| AI providers | `OCR_MOCK_MODE`, `FACE_MOCK_MODE`, `OPENAI_API_KEY`, `AWS_ACCESS_KEY_ID` | Set mock modes to `true` for development |
| Payments | `GATEWAY_STRIPE_SECRET_KEY`, `GATEWAY_STRIPE_WEBHOOK_SECRET` | Use `sk_test_` keys for development |
| Storage | `STORAGE_S3_ENDPOINT_URL`, `STORAGE_S3_BUCKET` | Points to MinIO locally, R2/S3 in production |
| Observability | `OTEL_EXPORTER_OTLP_ENDPOINT`, `SENTRY_DSN`, `LANGFUSE_*` | All optional; services degrade gracefully when unset |

## Documentation index

| Document | Description |
|----------|-------------|
| [`docs/demo-runbook.md`](docs/demo-runbook.md) | Step-by-step live demo script with recovery procedures |
| [`docs/runbook.md`](docs/runbook.md) | Operational runbook |
| [`docs/prod-readiness-2026-05-02.md`](docs/prod-readiness-2026-05-02.md) | Production-readiness audit: 17 fixes, test results, system state |
| [`docs/real-docs-eval-2026-04-28.md`](docs/real-docs-eval-2026-04-28.md) | Real-document evaluation results (21/29 fields matched on positive cases) |
| [`docs/future-work.md`](docs/future-work.md) | Deferred items: LLM ops layers 3-5, adversarial fixtures, bias evaluation, on-prem providers |
| [`k8s/README.md`](k8s/README.md) | Kubernetes deployment guide (k3s setup, secrets, Kustomize overlays, CI deploy) |
| [`load/README.md`](load/README.md) | Load testing setup and SLO definitions |
| [`services/web/src/README.md`](services/web/src/README.md) | Frontend code layout, path aliases, and dependency rules |
