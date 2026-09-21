#!/usr/bin/env bash
# backend/ の Rust workspace の依存関係ライセンスを再生成する。
# 依存クレートを追加/更新した後、コミット前にこれを実行して
# backend/THIRD-PARTY-LICENSES.html を最新化すること
# (.github/workflows/license-audit.yml が乖離を検知して失敗させる)。
set -euo pipefail
cd "$(dirname "$0")/../backend"

if ! command -v cargo-about >/dev/null 2>&1; then
    echo "==> Installing cargo-about..."
    cargo install cargo-about --locked --features cli
fi

echo "==> Generating THIRD-PARTY-LICENSES.html..."
cargo about generate about.hbs -o THIRD-PARTY-LICENSES.html

echo "==> Done! Review the diff and commit backend/THIRD-PARTY-LICENSES.html."
