#!/usr/bin/env bash
#
# Generates a self-signed TLS certificate for the dev nginx reverse proxy.
# The cert has SANs for localhost and docflow.local so you can use either.
#
# Run once before the first `docker compose up`. Certs land in nginx/certs/.
# In production, replace with Let's Encrypt / real CA certs.
#
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CERT_DIR="$PROJECT_ROOT/nginx/certs"
CERT_FILE="$CERT_DIR/docflow.crt"
KEY_FILE="$CERT_DIR/docflow.key"

mkdir -p "$CERT_DIR"

if [[ -f "$CERT_FILE" && -f "$KEY_FILE" ]]; then
  echo "[skip] certs already exist at $CERT_DIR"
  echo "       delete them and re-run to regenerate."
  exit 0
fi

openssl req -x509 -nodes -newkey rsa:2048 \
  -keyout "$KEY_FILE" \
  -out "$CERT_FILE" \
  -days 365 \
  -subj "/C=LB/ST=Beirut/L=Beirut/O=DocFlow Lebanon/CN=localhost" \
  -addext "subjectAltName = DNS:localhost,DNS:docflow.local,IP:127.0.0.1"

chmod 600 "$KEY_FILE"
chmod 644 "$CERT_FILE"

echo "[ok] self-signed cert generated:"
echo "     cert: $CERT_FILE"
echo "     key:  $KEY_FILE"
echo ""
echo "These are dev/demo certs. Replace with real CA certs in production."
