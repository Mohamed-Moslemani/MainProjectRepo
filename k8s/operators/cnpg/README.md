# CloudNativePG operator

DocFlow's prod overlay runs Postgres as a CNPG `Cluster` (3 instances,
synchronous replication, WAL archived to S3/MinIO). The operator
itself is cluster-scoped and only needs to be installed once per
cluster — it is **not** managed by the prod kustomize tree because
operator upgrades have their own cadence and we don't want a routine
app deploy to silently bump the operator version.

## One-time install

Pin a specific minor version. As of 2026-04 the current LTS is 1.24.

```bash
kubectl apply --server-side -f \
  https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.24/releases/cnpg-1.24.2.yaml
```

Verify:

```bash
kubectl -n cnpg-system get pods
kubectl get crd clusters.postgresql.cnpg.io
```

## Upgrades

Read the release notes; operator upgrades are non-disruptive (the
operator pod restarts, the Postgres clusters keep serving). Major
version bumps of Postgres itself (e.g. 16 → 17) require a planned
restart — bump `spec.imageName` in the `Cluster` and CNPG handles
the rolling restart with the standby promoted first.

## Why CNPG and not Patroni / Crunchy / Zalando

- CNPG is the only operator that doesn't ship its own custom
  Patroni fork; it speaks directly to Postgres replication APIs.
- Backup → S3 is a first-class CRD (`ObjectStore` + `Backup` +
  `ScheduledBackup`), not a sidecar bolt-on.
- Failover is synchronous-quorum-aware; no split-brain windows
  during network partitions.

## Backup verification

Once a month, restore the latest base backup into a scratch cluster
and run a `SELECT count(*)` against a known table. Untested backups
are not backups.
