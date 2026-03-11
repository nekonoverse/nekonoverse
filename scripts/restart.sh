#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Pulling latest images..."
docker compose pull

echo "==> Stopping nginx..."
docker compose stop nginx

echo "==> Recreating containers..."
docker compose up -d

echo "==> Done!"
