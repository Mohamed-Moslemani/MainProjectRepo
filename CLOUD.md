# Cloud mode — flipping between local and SaaS backends

DocFlow Lebanon ships with two compose layouts:

| Mode  | Command                                                                                   | Containers |
|-------|-------------------------------------------------------------------------------------------|-----------:|
| Local | `docker compose up -d`                                                                    |        ~22 |
| Cloud | `docker compose --env-file .env.cloud -f docker-compose.yml -f docker-compose.cloud.yml up -d` |    ~9 + Alloy |

Cloud mode disables the local observability + storage + error-tracking
stack and re-points every app service at managed SaaS endpoints. Code
in `services/*` is unchanged — only env vars differ.

## What gets replaced

| Replaces (local containers)                                                                     | With (managed)         |
|-------------------------------------------------------------------------------------------------|------------------------|
| `prometheus`, `grafana`, `jaeger`, `alertmanager`, `alertmanager_sink`, `pushgateway`, `postgres-exporter`, `redis-exporter` | **Grafana Cloud**      |
| `glitchtip`, `glitchtip_db`, `glitchtip_worker`, `glitchtip_migrate`                            | **Sentry**             |
| `minio`, `minio_init`                                                                            | **Cloudflare R2**      |
| (already cloud) `LANGFUSE_BASE_URL=https://cloud.langfuse.com`                                   | **Langfuse Cloud**     |
| (optional) `db`                                                                                  | **Neon**               |

Cloud mode adds one new container — `alloy` — which scrapes `/metrics`
from the local app services and `remote_write`s to Grafana Cloud
Mimir. It's the smallest possible bridge so you don't have to modify
app code to push metrics out.

Net change on a typical cloud-mode `docker compose ps`: ~22 → ~9
containers (gateway, gateway_worker, gateway_cron, ocr, face,
registry, web, nginx, db, redis, alloy).

## One-time setup

1. Create accounts and copy the credentials each provider gives you
   into `.env.cloud` (use `.env.cloud.example` as a template):

   - **Grafana Cloud** — sign up at https://grafana.com/auth/sign-up,
     go to your stack → "Send Metrics" panel for the Prometheus URL +
     username, then create a Cloud Access Policy token with
     `metrics:write` + `traces:write` scopes. The OTLP endpoint and
     a base64-encoded `Authorization: Basic` header come from the
     same panel ("Send OpenTelemetry Data").
   - **Sentry** — create an org at https://sentry.io, then **two
     projects**: one Python (backend DSN → `SENTRY_DSN`) and one
     React (frontend DSN → `VITE_SENTRY_DSN`). Different DSNs so
     PII filtering rules can differ.
   - **Cloudflare R2** — Cloudflare dashboard → R2 → Create bucket
     (`docflow-uploads`). Then R2 → Manage R2 API Tokens → Create
     with `Object Read & Write` on the bucket. The endpoint URL is
     `https://<account-id>.r2.cloudflarestorage.com`.
   - **Langfuse Cloud** — already pointed at `cloud.langfuse.com` in
     `.env.dev`. Override only if you want a separate cloud project.
   - **Neon** (optional) — sign up at https://neon.tech, create a
     project, copy the connection string. Then uncomment the `db:
     profiles: ["off"]` block in `docker-compose.cloud.yml`.

2. Copy the example file:

   ```bash
   cp .env.cloud.example .env.cloud
   ```

   Then fill in the blank values. `.env.cloud` is gitignored.

## Flipping between modes

```bash
# Local — full stack in containers
docker compose down
docker compose up -d

# Cloud — slim stack, SaaS for everything else
docker compose down
docker compose --env-file .env.cloud \
  -f docker-compose.yml -f docker-compose.cloud.yml up -d
```

The two modes share the same volumes (`postgres_data`, `uploads`,
`registry_data`, `redis`) so flipping doesn't lose dev data — only the
ancillary stacks (Prometheus TSDB, Grafana dashboards, GlitchTip
events, MinIO bucket) reset, since those are now elsewhere.

## What lives where in cloud mode

- **Dashboards** → grafana.com/orgs/&lt;your-org&gt; (free tier: unlimited
  dashboards, 14-day metrics retention).
- **Errors** → sentry.io/organizations/&lt;your-org&gt;/issues/.
- **Traces** → grafana.com → Explore → Tempo data source.
- **AI traces (OCR / classifier / LLM)** → cloud.langfuse.com.
- **Uploaded documents** → Cloudflare R2 dashboard → bucket browser.

## Rolling back

If anything breaks in cloud mode, `docker compose down && docker
compose up -d` puts you back on the all-local stack with no data
loss in the app DBs. Your cloud-side data (Grafana metrics, Sentry
issues, R2 objects) keeps accumulating until you delete it on each
provider's dashboard.

## Known cloud-mode caveats

- `gateway_cron` no longer pushes to a pushgateway. The
  `sweep_mukhtar_sla` script logs the metrics it would have pushed.
  If you need cloud-side visibility into cron sweep results, add a
  Prometheus pushgateway target to `monitoring/alloy/config.alloy`.
- Alertmanager routing rules from `monitoring/alertmanager/` don't
  carry over. Recreate them as Grafana Cloud alert rules in the
  Alerting section of your stack.
- Local Grafana dashboards under `monitoring/grafana/dashboards/` are
  JSON files — import them via Grafana Cloud's "Import Dashboard"
  flow if you want the same panels.
