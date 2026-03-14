#!/bin/sh
# Generate self-signed certs for Pleroma federation test domains.
set -e

CERT_DIR=/certs
mkdir -p "$CERT_DIR"

for domain in nekonoverse pleroma; do
  if [ ! -f "$CERT_DIR/$domain.crt" ]; then
    openssl req -x509 -newkey rsa:2048 -nodes \
      -keyout "$CERT_DIR/$domain.key" \
      -out "$CERT_DIR/$domain.crt" \
      -days 1 \
      -subj "/CN=$domain" \
      -addext "subjectAltName=DNS:$domain" \
      2>/dev/null
    echo "Generated cert for $domain"
  fi
done
