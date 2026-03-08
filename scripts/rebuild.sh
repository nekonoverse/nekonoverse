#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

echo "==> Rebuilding and starting containers..."
docker compose up -d --build

echo "==> Pruning build cache..."
docker buildx prune -f

echo "==> Done!"
