#!/bin/sh
# Generate CA and domain certs for Mitra federation test.
set -e

CERT_DIR=/certs
mkdir -p "$CERT_DIR"

# Generate CA if not present
if [ ! -f "$CERT_DIR/ca.crt" ]; then
  openssl req -x509 -newkey rsa:2048 -nodes \
    -keyout "$CERT_DIR/ca.key" \
    -out "$CERT_DIR/ca.crt" \
    -days 1 \
    -subj "/CN=Test Federation CA" \
    2>/dev/null
  echo "Generated CA cert"
fi

# Generate domain certs signed by CA
for domain in nekonoverse mitra; do
  if [ ! -f "$CERT_DIR/$domain.crt" ]; then
    # Create CSR
    openssl req -newkey rsa:2048 -nodes \
      -keyout "$CERT_DIR/$domain.key" \
      -out "$CERT_DIR/$domain.csr" \
      -subj "/CN=$domain" \
      -addext "subjectAltName=DNS:$domain" \
      2>/dev/null
    # Sign with CA
    openssl x509 -req \
      -in "$CERT_DIR/$domain.csr" \
      -CA "$CERT_DIR/ca.crt" \
      -CAkey "$CERT_DIR/ca.key" \
      -CAcreateserial \
      -out "$CERT_DIR/$domain.crt" \
      -days 1 \
      -copy_extensions copyall \
      2>/dev/null
    rm -f "$CERT_DIR/$domain.csr"
    echo "Generated cert for $domain (signed by CA)"
  fi
done
