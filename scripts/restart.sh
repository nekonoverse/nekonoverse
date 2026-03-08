#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Pulling latest images..."
docker compose pull

echo "==> Recreating containers..."
docker compose up -d

echo "==> Restarting nginx..."
docker compose restart nginx

echo "==> Done!"
