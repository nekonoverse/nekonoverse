#!/bin/bash
set -e

# Trust the test CA cert for federation with self-signed certs
if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/test-ca.crt
  update-ca-certificates 2>/dev/null || true
fi

# Wait for PostgreSQL
until pg_isready -h "$DB_HOST" -U "$DB_USER" -q 2>/dev/null; do
  echo "Waiting for PostgreSQL..."
  sleep 1
done

# Wait for Redis
until redis-cli -h "$REDIS_HOST" ping 2>/dev/null | grep -q PONG; do
  echo "Waiting for Redis..."
  sleep 1
done

# Initialize database
echo "Setting up database..."
SAFETY_ASSURED=1 bundle exec rails db:setup 2>/dev/null || bundle exec rails db:migrate

# Enable open registration
bundle exec rails runner "Setting.registrations_mode = 'open'" 2>/dev/null || true

# Start Puma web server
exec bundle exec puma -C config/puma.rb
