#!/bin/bash
set -e

# Trust the test CA cert for federation with self-signed certs
if [ -f /certs/ca.crt ]; then
  cp /certs/ca.crt /usr/local/share/ca-certificates/test-ca.crt
  update-ca-certificates 2>/dev/null || true
fi

# Wait for PostgreSQL (use Ruby since pg_isready may not be installed)
until bundle exec ruby -e "require 'pg'; PG.connect(host: ENV['DB_HOST'], port: ENV.fetch('DB_PORT', 5432), user: ENV['DB_USER'], password: ENV['DB_PASS'], dbname: 'postgres')" 2>/dev/null; do
  echo "Waiting for PostgreSQL..."
  sleep 1
done

# Wait for Redis (use Ruby since redis-cli may not be installed)
until bundle exec ruby -e "require 'redis'; Redis.new(host: ENV['REDIS_HOST'], port: ENV.fetch('REDIS_PORT', 6379)).ping" 2>/dev/null; do
  echo "Waiting for Redis..."
  sleep 1
done

# Initialize database
echo "Setting up database..."
SAFETY_ASSURED=1 bundle exec rails db:setup 2>/dev/null || bundle exec rails db:migrate

# Enable open registration
bundle exec rails runner "Setting.registrations_mode = 'open'" 2>/dev/null || true

# Disable email MX check for testing (allows example.com emails)
bundle exec rails runner "Setting.min_invite_role = 'user'" 2>/dev/null || true

# Create test user bob (idempotent)
RAILS_ENV=production bundle exec tootctl accounts create bob --email bob@mastodon --confirmed 2>/dev/null || true
# Set known password for bob
bundle exec rails runner "
  account = Account.find_local('bob')
  if account
    user = account.user
    user.password = 'Password1234!'
    user.save!(validate: false)
  end
" 2>/dev/null || true

# Start Puma web server
exec bundle exec puma -C config/puma.rb
