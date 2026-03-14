#!/bin/sh
# Add test CA cert to system trust store before starting Pleroma
if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/test-federation-ca.crt
  update-ca-certificates 2>/dev/null
  echo "Added test CA cert to trust store"
fi

# Execute the original entrypoint
exec /app/start.sh
