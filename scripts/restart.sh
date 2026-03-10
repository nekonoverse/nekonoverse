#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Stopping nginx..."
docker compose stop nginx

echo "==> Pulling latest images..."
docker compose pull

echo "==> Recreating containers..."
docker compose up -d

echo "==> Done!"
