#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
    echo "Usage: $0 [--restart-nginx]"
    echo "  --restart-nginx  nginx を事前に停止して再起動する (TCP 構成時に必要)"
    exit 1
}

restart_nginx=false
for arg in "$@"; do
    case "$arg" in
        --restart-nginx) restart_nginx=true ;;
        -h|--help) usage ;;
        *) echo "Unknown option: $arg"; usage ;;
    esac
done

echo "==> Pulling latest images..."
docker compose pull

if [ "$restart_nginx" = true ]; then
    echo "==> Stopping nginx..."
    docker compose stop nginx
fi

echo "==> Recreating containers..."
docker compose up -d

echo "==> Done!"
