#!/usr/bin/env bash
# OAuth authorize URL を生成するスクリプト
#
# Usage:
#   ./scripts/oauth-url.sh https://example.com [アプリ名] [スコープ]
#
# Examples:
#   ./scripts/oauth-url.sh https://nekonoverse.cloud
#   ./scripts/oauth-url.sh http://localhost:8000 "TestApp" "read write follow"
#   ./scripts/oauth-url.sh https://nekonoverse.cloud "Elk" "read write follow push"
set -euo pipefail

BASE_URL="${1:?Usage: $0 <base-url> [app-name] [scopes]}"
APP_NAME="${2:-TestApp}"
SCOPES="${3:-read write follow}"
REDIRECT_URI="urn:ietf:wg:oauth:2.0:oob"

resp=$(curl -sf "${BASE_URL}/api/v1/apps" \
  -H "Content-Type: application/json" \
  -d "{\"client_name\":\"${APP_NAME}\",\"redirect_uris\":\"${REDIRECT_URI}\",\"scopes\":\"${SCOPES}\"}")

client_id=$(echo "$resp" | jq -r .client_id)
client_secret=$(echo "$resp" | jq -r .client_secret)

echo "client_id:     ${client_id}"
echo "client_secret: ${client_secret}"
echo ""
echo "Authorize URL:"
echo "${BASE_URL}/oauth/authorize?response_type=code&client_id=${client_id}&redirect_uri=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${REDIRECT_URI}'))")&scope=$(python3 -c "import urllib.parse; print(urllib.parse.quote('${SCOPES}'))")"
