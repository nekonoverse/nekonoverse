#!/bin/sh
set -e

# Add test CA cert to system trust store
if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/test-federation-ca.crt
  update-ca-certificates 2>/dev/null || true
  echo "Added test CA cert to trust store"
fi

# Create web_client_dir (can be empty)
mkdir -p /var/lib/mitra/www

# Create test user bob after server starts (background)
(
  sleep 10
  mitra create-account bob password123 user 2>/dev/null || true
  echo "Created test user bob"
) &

# Start Mitra server
exec mitra server
