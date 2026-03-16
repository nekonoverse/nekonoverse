#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
    cat <<EOF
Usage: $0 <BACKUP_FILE>

Nekonoverse リストアスクリプト。
バックアップアーカイブから PostgreSQL, Valkey, nekono3s, .env を復元する。

Arguments:
  BACKUP_FILE   .tar.gz または .tar.gz.gpg バックアップファイル

Options:
  -h, --help    このヘルプを表示
EOF
    exit 0
}

if [[ $# -lt 1 ]] || [[ "$1" == "-h" ]] || [[ "$1" == "--help" ]]; then
    usage
fi

BACKUP_FILE="$1"

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "Error: File not found: $BACKUP_FILE"
    exit 1
fi

BACKUP_FILE=$(cd "$(dirname "$BACKUP_FILE")" && pwd)/$(basename "$BACKUP_FILE")

# --- 確認プロンプト ---
echo "WARNING: This will overwrite current data with the backup."
echo "  Backup: $BACKUP_FILE"
echo ""
read -rp "Continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then
    echo "Aborted."
    exit 0
fi

# --- 1. コンテナで展開 ---
echo "==> Extracting backup..."
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

GPG_ARGS=""
IS_GPG=""
if [[ "$BACKUP_FILE" == *.gpg ]]; then
    IS_GPG="1"
    GPG_ARGS="-v ${HOME}/.gnupg:/gnupg:ro"
fi

# shellcheck disable=SC2086
docker run --rm \
    -v "$BACKUP_FILE:/backup/archive:ro" \
    -v "$TMP_DIR:/restore" \
    $GPG_ARGS \
    alpine:latest sh -c "
        set -e
        if [ -n '${IS_GPG}' ]; then
            apk add --no-cache gnupg > /dev/null 2>&1
            echo '  gpg decrypt...'
            gpg --homedir /gnupg --batch \
                --output /tmp/archive.tar.gz --decrypt /backup/archive
            tar xzf /tmp/archive.tar.gz -C /restore
        else
            tar xzf /backup/archive -C /restore
        fi
        echo '  extracted.'
    "

# 展開内容チェック
if [[ ! -f "$TMP_DIR/db.dump" ]]; then
    echo "Error: db.dump not found in backup archive."
    exit 1
fi

# --- 2. サービス停止 ---
echo "==> Stopping app and worker..."
docker compose stop app worker

# --- 3. PostgreSQL リストア ---
echo "==> Restoring PostgreSQL..."
docker compose exec -T postgresql pg_restore -U nekonoverse -d nekonoverse \
    --clean --if-exists < "$TMP_DIR/db.dump" || true

# --- 4. Valkey リストア ---
if [[ -f "$TMP_DIR/valkey/dump.rdb" ]]; then
    echo "==> Restoring Valkey..."
    docker compose cp "$TMP_DIR/valkey/dump.rdb" valkey:/data/dump.rdb
    docker compose restart valkey
else
    echo "==> Skipping Valkey (no dump.rdb in backup)"
fi

# --- 5. nekono3s リストア ---
if [[ -d "$TMP_DIR/nekono3s" ]]; then
    echo "==> Restoring nekono3s..."
    rm -rf ./volumes/nekono3s/*
    cp -a "$TMP_DIR/nekono3s/." ./volumes/nekono3s/
else
    echo "==> Skipping nekono3s (not in backup)"
fi

# --- 6. .env リストア ---
if [[ -f "$TMP_DIR/env.bak" ]]; then
    if [[ -f ".env" ]]; then
        read -rp "Overwrite .env with backup version? (yes/no): " OVERWRITE_ENV
        if [[ "$OVERWRITE_ENV" == "yes" ]]; then
            cp "$TMP_DIR/env.bak" .env
            echo "  .env restored."
        else
            echo "  .env kept as-is."
        fi
    else
        cp "$TMP_DIR/env.bak" .env
        echo "  .env restored."
    fi
fi

# --- 7. マイグレーション + スキーマチェック ---
echo "==> Starting app for migrations..."
docker compose start app
echo "==> Running migrations..."
docker compose exec app alembic upgrade head
echo "==> Checking schema..."
docker compose exec app python -m scripts.check_schema

# --- 8. 全サービス再起動 ---
echo "==> Restarting all services..."
docker compose up -d

echo "==> Restore complete!"
