#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

usage() {
    cat <<EOF
Usage: $0 [OPTIONS]

Nekonoverse バックアップスクリプト。
PostgreSQL, Valkey, nekono3s, .env を一括バックアップする。
専用の Alpine コンテナでデータを ro マウントし tar 圧縮する。

Options:
  -o, --output DIR         出力先ディレクトリ (default: ./backups)
  -r, --retain DAYS        保持日数。古いバックアップを自動削除 (default: 7)
  -g, --gpg-recipient ID   GPG 公開鍵の受信者ID。指定時に暗号化
  -h, --help               このヘルプを表示

Examples:
  $0                                         # 平文バックアップ
  $0 -g admin@example.com                    # GPG 暗号化バックアップ
  $0 -o /mnt/backup -r 30 -g admin@example   # 外部ストレージ、30日保持

cron:
  0 3 * * * /path/to/nekonoverse/scripts/backup.sh -g admin@example.com >> /var/log/nekonoverse-backup.log 2>&1
EOF
    exit 0
}

OUTPUT_DIR="./backups"
RETAIN_DAYS=7
GPG_RECIPIENT=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        -o|--output)   OUTPUT_DIR="$2"; shift 2 ;;
        -r|--retain)   RETAIN_DAYS="$2"; shift 2 ;;
        -g|--gpg-recipient) GPG_RECIPIENT="$2"; shift 2 ;;
        -h|--help)     usage ;;
        *) echo "Unknown option: $1"; usage ;;
    esac
done

TIMESTAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE_NAME="nekonoverse-backup-${TIMESTAMP}"

mkdir -p "$OUTPUT_DIR"

# --- 1. PostgreSQL pg_dump ---
echo "==> Dumping PostgreSQL..."
DUMP_TMP=$(mktemp)
trap 'rm -f "$DUMP_TMP"' EXIT
docker compose exec -T postgresql pg_dump -U nekonoverse -Fc nekonoverse > "$DUMP_TMP"

# --- 2. Valkey BGSAVE ---
echo "==> Triggering Valkey BGSAVE..."
docker compose exec -T valkey valkey-cli BGSAVE > /dev/null 2>&1 || true
sleep 2

# --- 3. バックアップコンテナで tar (+gpg) ---
echo "==> Creating archive in container..."

GPG_ARGS=""
if [[ -n "$GPG_RECIPIENT" ]]; then
    GPG_ARGS="-v ${HOME}/.gnupg:/gnupg:ro"
fi

# shellcheck disable=SC2086
docker run --rm \
    -v "$DUMP_TMP:/data/db.dump:ro" \
    -v "./volumes/valkey:/data/valkey:ro" \
    -v "./volumes/nekono3s:/data/nekono3s:ro" \
    -v "$PWD/.env:/data/env.bak:ro" \
    -v "$(cd "$OUTPUT_DIR" && pwd):/backups" \
    $GPG_ARGS \
    alpine:latest sh -c "
        set -e
        apk add --no-cache tar > /dev/null 2>&1
        if [ -d /gnupg ]; then
            apk add --no-cache gnupg > /dev/null 2>&1
        fi
        echo '  tar...'
        tar czf /tmp/${ARCHIVE_NAME}.tar.gz --xattrs -C /data .
        if [ -d /gnupg ]; then
            echo '  gpg encrypt...'
            gpg --homedir /gnupg --trust-model always --batch \
                --recipient '${GPG_RECIPIENT}' \
                --output /backups/${ARCHIVE_NAME}.tar.gz.gpg \
                --encrypt /tmp/${ARCHIVE_NAME}.tar.gz
        else
            mv /tmp/${ARCHIVE_NAME}.tar.gz /backups/
        fi
        echo '  done.'
    "

# --- 4. ローテーション ---
if [[ "$RETAIN_DAYS" -gt 0 ]]; then
    echo "==> Rotating backups older than ${RETAIN_DAYS} days..."
    find "$OUTPUT_DIR" -name "nekonoverse-backup-*" -mtime +"$RETAIN_DAYS" -delete 2>/dev/null || true
fi

# --- 完了 ---
if [[ -n "$GPG_RECIPIENT" ]]; then
    OUTPUT_FILE="${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz.gpg"
else
    OUTPUT_FILE="${OUTPUT_DIR}/${ARCHIVE_NAME}.tar.gz"
fi
SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
echo "==> Backup complete: ${OUTPUT_FILE} (${SIZE})"
