# DocFlow on Kubernetes

Deployment manifests for running the full DocFlow Lebanon stack on
Kubernetes. Built against single-node k3s on a Hetzner VPS, but the
base manifests work on any standard cluster with an nginx-ingress
controller and cert-manager.

## Layout

```
k8s/
├── base/                  Kustomize base — full stack, cluster-agnostic
│   ├── namespace.yaml
│   ├── configmap.yaml     Non-sensitive env
│   ├── secrets.example.yaml   Template — copy to ../secrets.yaml (gitignored)
│   ├── storage/
│   ├── postgres/ registry-postgres/ redis/
│   ├── gateway/ ocr/ face/ registry/ web/
│   └── ingress/           Ingress + cert-manager ClusterIssuer
└── overlays/
    ├── dev/               Local kind/k3d, mock mode on, no TLS
    └── prod/              Real cluster, real TLS via Let's Encrypt
```

## One-time cluster setup (Hetzner + k3s)

### 1. Provision the VPS
- Hetzner Cloud → new project → new server
- Ubuntu 24.04, CPX21 (3 vCPU / 4 GB, €5.83/mo) or larger
- Add your SSH key
- Note the public IPv4

### 2. Install k3s (on the server)

```bash
ssh root@<your-ip>
curl -sfL https://get.k3s.io | sh -s - \
  --write-kubeconfig-mode 644 \
  --disable traefik
```

### 3. Install ingress-nginx + cert-manager

```bash
# ingress-nginx
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/controller-v1.11.2/deploy/static/provider/baremetal/deploy.yaml

# cert-manager (CRDs + controller)
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/download/v1.15.3/cert-manager.yaml

# Wait for both to come up
kubectl -n ingress-nginx rollout status deploy/ingress-nginx-controller --timeout=120s
kubectl -n cert-manager rollout status deploy/cert-manager --timeout=120s
```

### 4. Point DNS at the server
In your registrar's DNS panel:
```
A  @  → <your-ip>
A  *  → <your-ip>
```
Wait ~5 min for propagation.

### 5. Grab the kubeconfig to your laptop
On the server:
```bash
cat /etc/rancher/k3s/k3s.yaml
```
Copy the output, replace `127.0.0.1` with your public IP on the
`server:` line, and save it locally as `~/.kube/docflow-prod.yaml`.
Test with:
```bash
KUBECONFIG=~/.kube/docflow-prod.yaml kubectl get nodes
```

## Secrets

Kubernetes secrets are applied manually once per cluster — they don't
live in the repo. Start from the template:

```bash
cp k8s/base/secrets.example.yaml k8s/secrets.yaml
# edit k8s/secrets.yaml and fill in the real AWS / Stripe / SMTP / JWT values
kubectl apply -f k8s/secrets.yaml
```

Plus the Google Vision service account JSON (kept as a file, not inline):

```bash
kubectl -n docflow create secret generic docflow-google-vision \
  --from-file=google-vision.json=./credentials/google-vision.json
```

`k8s/secrets.yaml` is in `.gitignore` — never commit it.

## Substitute your domain into the prod overlay

```bash
sed -i '' "s/DOMAIN_PLACEHOLDER/docflow.yourdomain.com/g" k8s/overlays/prod/kustomization.yaml
# (GNU sed: drop the '' after -i)
```

(Or let CI do it — set `DOCFLOW_DOMAIN` as a repository variable in
GitHub Actions and the `deploy` workflow will patch it at apply time.)

## Deploy from your laptop

```bash
export KUBECONFIG=~/.kube/docflow-prod.yaml
kubectl kustomize k8s/overlays/prod | kubectl apply -f -

# Watch the rollout
kubectl -n docflow get pods -w
```

First rollout takes ~2 min. cert-manager takes another 1–2 min to
issue the Let's Encrypt cert.

## Deploy from CI (GitHub Actions)

On every push to `main` or `develop`, `.github/workflows/deploy.yml`:

1. Builds + pushes 5 images to GHCR, tagged by git SHA
2. Pins the prod overlay to those SHAs via `kustomize edit set image`
3. Substitutes `DOCFLOW_DOMAIN` for `DOMAIN_PLACEHOLDER`
4. `kubectl apply -k k8s/overlays/prod`
5. Waits for each Deployment to roll out

Required GitHub Actions configuration:

| Name | Type | Value |
|------|------|-------|
| `KUBECONFIG` | secret | full contents of your kubeconfig file |
| `DOCFLOW_DOMAIN` | variable | e.g. `docflow.yourdomain.com` |

Set these under **Repo → Settings → Secrets and variables → Actions**.

## Local kind/k3d dev

```bash
kind create cluster --name docflow
# Build all images locally first:
docker compose build
# Load them into kind:
for svc in gateway ocr face registry web; do
  kind load docker-image finalproject-${svc}:latest --name docflow
done
# Deploy the dev overlay (mock AI, no TLS):
kubectl kustomize k8s/overlays/dev | kubectl apply -f -
# Port-forward the ingress controller and open http://localhost:8080
kubectl -n ingress-nginx port-forward svc/ingress-nginx-controller 8080:80
```

## Common operations

**Rollback one service**:
```bash
kubectl -n docflow rollout undo deployment/gateway
```

**Check a failing pod**:
```bash
kubectl -n docflow describe pod -l app=gateway
kubectl -n docflow logs -l app=gateway --tail=200
```

**Exec into a pod**:
```bash
kubectl -n docflow exec -it deploy/gateway -- bash
```

**Postgres backup**:
```bash
kubectl -n docflow exec postgres-0 -- pg_dump -U docflow docflow > backup.sql
```

**Force a cert-manager renewal**:
```bash
kubectl -n docflow delete certificate docflow-tls
# cert-manager recreates it from the Ingress annotation
```

## What's NOT here (deliberate scope cuts)

These are production-grade items worth adding if this goes to real
Ministry deployment. For a pitchable demo they're out of scope:

- **Multi-replica Postgres with failover** — currently 1 pod + PVC
- **HorizontalPodAutoscaler** — static replica counts
- **NetworkPolicy** — all pods can talk to each other inside the ns
- **PodDisruptionBudget** — single-node anyway
- **SealedSecrets / External Secrets / Vault** — current design uses
  plain K8s Secrets (not in git but decodable with cluster access)
- **S3-backed uploads** — currently a hostPath PV (single-node only).
  Multi-node needs MinIO or external S3 and a service refactor.
- **Centralized logs (Loki / Elastic)** — currently `kubectl logs`
- **Service mesh** — none; direct service-to-service HTTP
