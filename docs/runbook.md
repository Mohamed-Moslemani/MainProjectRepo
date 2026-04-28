# DocFlow on-call runbook

For each alert: **what it means**, **what to check first**, and the
exact commands to run. Keep this file in sync with
`monitoring/prometheus/alerts.yml` — when you add an alert there,
add a section here and link it via `runbook_url`.

Severity convention:

- **critical** — pages PagerDuty. User-facing breakage or imminent
  data loss. Acknowledge within 5 min.
- **warning** — Slack `#docflow-alerts`. Investigate next business
  hour unless it persists or compounds.

## Quick links

- Grafana: <http://localhost:3001> (admin / docflow)
- Prometheus: <http://localhost:9090> · `/alerts` · `/targets`
- Alertmanager: <http://localhost:9093> · silences live here
- Jaeger: <http://localhost:16686>
- GlitchTip: <http://localhost:8005>
- MinIO console: <http://localhost:9001>

In prod, replace `localhost` with the cluster's domain.

## First-five-minutes checklist

1. Open Grafana → service-health dashboard. Are 5xx rate or p95
   spiking on a *single* service or all of them?
2. `kubectl -n docflow get pods -o wide` (or `docker compose ps`) —
   any pod restarting or in `CrashLoopBackOff`?
3. `/alerts` in Prometheus — is more than one alert firing? If yes,
   read the inhibition graph (a `ServiceDown` will suppress derived
   warnings; the silenced ones are usually consequences not causes).
4. Recent deploy? `kubectl -n docflow rollout history deployment/<svc>`
   then `git log --oneline -10` to correlate.
5. If the user-facing API is down and the cause isn't obvious in
   60 seconds, **roll back first**, debug second:
   `kubectl -n docflow rollout undo deployment/gateway`.

## Per-alert playbooks

### ServiceDown — critical

A scrape target has been `up == 0` for 30s.

```bash
# Which target?
kubectl -n docflow get pods -l app=<service>
kubectl -n docflow describe pod <pod>          # events, OOMKilled?
kubectl -n docflow logs <pod> --tail=200
kubectl -n docflow logs <pod> --previous       # if it crashed
```

Most common causes: image pull error after a tag bump, OOM (bump
`resources.limits.memory` in the Deployment), failed readiness
probe (gateway depends on Postgres + Redis being reachable).

### HighErrorRate — warning

5xx rate > 5% on a service for 1 min.

```bash
# Top error endpoints in the last 15 min
kubectl -n docflow logs deploy/<service> --since=15m | grep '"status": 5'
# Trace: open Jaeger, filter by service + http.status_code = 500
```

Check GlitchTip — a Python exception will surface there with the
full stack. If the spike correlates with a specific endpoint, look
at recent migrations affecting its tables.

### HighLatency — warning

p95 > 2s on a service for 2 min.

- Gateway: usually downstream (`ocr`, `face`, `registry`) latency
  bleeding through. Check those services' p95 first.
- DB-bound: `pg_stat_activity` for long-running queries:
  ```sql
  SELECT pid, now() - query_start AS duration, state, query
  FROM pg_stat_activity
  WHERE state != 'idle' AND query_start < now() - interval '5s'
  ORDER BY duration DESC;
  ```
- Pool exhaustion: `PostgreSQLHighConnections` would also be firing.

### PostgreSQLDown — critical

`pg_up == 0` for 30s.

- Single-replica dev: `docker compose logs db`. Disk full? OOM?
- CNPG prod: `kubectl -n docflow get cluster postgres` — has the
  primary failed over? Operator promotes a standby in ~10s; if it's
  longer than that, `kubectl -n docflow describe cluster postgres`
  for the operator's progress notes. If both standbys are also
  down, restore from latest backup (see "PITR restore" below).

### PostgreSQLHighConnections — warning

`(active connections) / max_connections > 0.8` for 2 min.

Almost always a connection-pool leak in the gateway. Check `pg_stat_activity` for connections held open with `state = 'idle in
transaction'`. Restart the gateway if you can't find the leak —
buys time, then file an issue with the offending endpoint.

### RedisDown — critical

`redis_up == 0` for 30s.

Rate limiting, the Arq queue, and the email outbox all use Redis.
The gateway falls back to the in-process BackgroundTasks path on
queue failure (see `cases.py` submit handler), so case submissions
still work in degraded mode — but rate limits are bypassed and
emails will start piling up in the outbox.

```bash
docker compose logs --tail=200 redis
docker compose exec redis redis-cli INFO memory
```

### HighPaymentFailureRate — warning

Stripe failures spiking. Check Stripe dashboard
(<https://dashboard.stripe.com/test/payments>) for the underlying
decline reason. If it's `card_declined` across many users, the
issue is theirs not ours; if it's `processing_error` or our
webhook signature is failing, look at gateway logs:

```bash
docker compose logs gateway --since=15m | grep -i 'stripe\|webhook'
```

### RateLimitStorm — warning

Lots of 429s. Either a real abuse pattern or a misconfigured
client. Open the audit log filtered by `ip` to see the source:

```sql
SELECT ip, count(*) FROM audit_logs
WHERE action = 'rate_limit_blocked' AND created_at > now() - interval '15 min'
GROUP BY ip ORDER BY 2 DESC LIMIT 20;
```

If a single IP, block at the ingress (Cloudflare WAF rule). If
spread broad, the limit is too tight — bump
`GATEWAY_RATE_LIMIT_PER_MINUTE` in the prod overlay.

### HighOCRErrorRate / OCRLatencyHigh — warning

Google Cloud Vision is the most likely culprit. Check the GCP
status page (<https://status.cloud.google.com>) and the OCR pod's
own metrics:

```bash
docker compose logs ocr --since=10m | grep -i 'vision\|google'
```

If GCV is healthy but our error rate is up, look for image-quality
regressions — a recent change to the `imageQuality.js` thresholds
or the OCR mock fixture would do it.

### FaceRejectionSpike / LivenessFailureSpike — warning

Either AWS Rekognition is degraded or someone shipped tighter
thresholds. The risk-scoring weights live in
`services/gateway/app/services/risk.py`; a recent commit changing
those is the prime suspect. If genuinely upstream:

```bash
# liveness session count + status breakdown last hour
SELECT
  liveness_result->>'status' AS status,
  liveness_result->>'liveness_passed' AS passed,
  count(*)
FROM cases WHERE updated_at > now() - interval '1 hour'
GROUP BY 1, 2;
```

### PipelineLatencyHigh — warning

Submit-to-decision exceeded its budget. The pipeline runs in the
Arq worker (`gateway-worker` deploy). Common causes: worker
backlog (HPA didn't scale fast enough — check
`kubectl top pod -l app=gateway-worker` and bump `replicas`),
slow downstream service, slow DB.

```bash
kubectl -n docflow logs deploy/gateway-worker --tail=200
# Arq backlog
docker compose exec redis redis-cli LLEN arq:queue
```

### RiskScoreDriftHigh — warning

The auto-rejection rate has shifted noticeably from baseline. This
is intentional behaviour from the drift alert in
`drift_alerts.yml` — it's *not* a bug, it's a signal to retrain or
tune. Compare the last 7 days vs the prior 7:

```sql
SELECT
  date_trunc('day', updated_at) AS day,
  status,
  count(*)
FROM cases
WHERE updated_at > now() - interval '14 days'
GROUP BY 1, 2 ORDER BY 1 DESC, 2;
```

If the shift is paired with a recent risk-scoring code change,
revert and ramp slowly via flag.

### RegistryNoMatchSpike — warning

Civil registry lookups are returning "not found" at a rate that
suggests either the seed data drifted or the matching key changed.
Confirm the registry service pod is healthy, then check whether
the most recent failures are concentrated in a single
`registry_place` (a syncing issue with that governorate's data).

## PITR restore (CNPG, prod)

Last-resort playbook. Loses any unbackup-copied transactions
between the chosen restore time and now.

```bash
# Pick a target time (UTC)
TARGET="2026-04-28T07:30:00.000000Z"

# Tell the operator to spin up a new cluster from the latest base
# backup, replaying WAL up to TARGET.
kubectl -n docflow apply -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: postgres-restore
spec:
  instances: 1
  bootstrap:
    recovery:
      source: postgres
      recoveryTarget:
        targetTime: "${TARGET}"
  externalClusters:
    - name: postgres
      barmanObjectStore:
        destinationPath: s3://docflow-pgbackup/postgres
        endpointURL: http://minio.docflow.svc.cluster.local:9000
        s3Credentials:
          accessKeyId:
            name: postgres-backup-credentials
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: postgres-backup-credentials
            key: ACCESS_SECRET_KEY
EOF
```

When the new cluster reports healthy, switch the gateway's
`postgres` ExternalName to point at `postgres-restore-rw`, verify,
then take the original cluster down. Document the restore in the
incident postmortem.

## Postmortem template

Every PagerDuty page gets a postmortem within 48 hours, even if
the resolution was "rolled back, root cause unclear". Use:

- **Detection** — alert that fired, who acked, time
- **Impact** — # cases stuck / customers affected / payment failure window
- **Timeline** — UTC, one line per event, linked to logs/traces
- **Root cause** — the one thing that, if undone, would have prevented this
- **Fix** — PR or runbook change
- **Action items** — alert tuning, missing test, missing docs (each with owner + due date)

Keep them in `docs/postmortems/<date>-<slug>.md`. They're how the
team learns; they're not a tool for assigning blame.
