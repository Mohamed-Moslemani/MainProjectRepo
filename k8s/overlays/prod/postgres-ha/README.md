# Prod Postgres — CloudNativePG

Replaces the base single-replica StatefulSets with 3-instance CNPG
`Cluster` resources (sync replication, WAL → MinIO, 30-day PITR).

## Prerequisites (one-time per cluster)

1. **Operator install** — see [k8s/operators/cnpg/README.md].

2. **Backup credentials** — a MinIO user with read/write on the
   `docflow-pgbackup` bucket:

   ```bash
   kubectl -n docflow create secret generic postgres-backup-credentials \
     --from-literal=ACCESS_KEY_ID=<minio-key> \
     --from-literal=ACCESS_SECRET_KEY=<minio-secret>
   ```

3. **App credentials** — the role CNPG creates for the app to log in
   as. Pick strong passwords; these go into the gateway's
   `GATEWAY_DATABASE_URL` secret too.

   ```bash
   kubectl -n docflow create secret generic postgres-app-credentials \
     --from-literal=username=docflow \
     --from-literal=password='<strong-random>'

   kubectl -n docflow create secret generic registry-postgres-app-credentials \
     --from-literal=username=registry \
     --from-literal=password='<strong-random>'
   ```

4. **Bucket** — pre-create `docflow-pgbackup` on MinIO (the
   `minio_init` job already creates `docflow-uploads`; extend it
   for prod).

## Migrating from the base StatefulSet

If you've been running on the single-pod StatefulSet and now want
to cut over without losing data:

```bash
# 1. pg_dump from the old pod
kubectl -n docflow exec -it postgres-0 -- \
  pg_dump -U docflow -d docflow -Fc -f /tmp/docflow.dump
kubectl -n docflow cp postgres-0:/tmp/docflow.dump ./docflow.dump

# 2. apply the prod overlay (creates the CNPG Cluster, deletes the
#    old StatefulSet — old PVC remains until you delete it)
kubectl apply -k k8s/overlays/prod

# 3. wait for the CNPG primary to be ready
kubectl -n docflow get cluster postgres -w

# 4. restore
kubectl -n docflow cp ./docflow.dump postgres-1:/tmp/restore.dump
kubectl -n docflow exec -it postgres-1 -- \
  pg_restore -U docflow -d docflow /tmp/restore.dump
```

For a green-field deploy you can skip steps 1 and 4 — alembic on
gateway startup will create the schema in the empty CNPG database.

## Connection routing

Apps connect to `postgres:5432` (or `registry-postgres:5432`). The
prod overlay rewrites those Services to `ExternalName` records that
forward to `postgres-rw.docflow.svc.cluster.local` and
`registry-postgres-rw.docflow.svc.cluster.local`. CNPG keeps those
`-rw` endpoints pointed at the current primary, so failover is
transparent to the app (a few seconds of connection errors during
the promotion window, then writes resume).

## Failover test (do this in staging first)

```bash
# Find the primary
kubectl -n docflow get pods -l cnpg.io/cluster=postgres -L role

# Force-delete it
kubectl -n docflow delete pod postgres-1   # whichever is primary

# Watch the operator promote a standby
kubectl -n docflow get cluster postgres -w
```

The whole exchange should finish in ~10–15s. Run it during low
traffic the first time.

## Backups

- `ScheduledBackup` triggers a base backup nightly (03:00 / 03:30
  UTC). WAL is streamed continuously between bases.
- Retention: 30 days. Older bases + their WAL are pruned.
- **Verify monthly**: restore the latest backup into a scratch
  cluster and run a sanity query. Untested backups aren't backups.
