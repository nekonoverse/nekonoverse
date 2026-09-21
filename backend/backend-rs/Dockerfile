# --- Build stage ---
# backend-rs は backend/native (PyO3 拡張) と同じ Cargo workspace に属するが、
# `--package` を指定することで native (Python インタプリタが無いとビルド
# スクリプトすら実行できない) をビルド対象から除外できる。
FROM rust:1-slim AS builder
WORKDIR /workspace
COPY Cargo.toml Cargo.lock ./
COPY rust-core rust-core
COPY backend-rs backend-rs
# native は workspace メンバーとして manifest 解決に必要だが、ビルド対象には
# しない (Python インタプリタが無いと native のビルドスクリプトが失敗するため)。
COPY native/Cargo.toml native/Cargo.toml
RUN mkdir -p native/src && echo "fn _unused() {}" > native/src/lib.rs
RUN cargo build --release --package nekonoverse-backend-rs

# --- Runtime stage ---
FROM debian:13-slim AS production
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 853 nekonoverse-rs \
    && useradd --system --no-create-home --uid 853 --gid 853 nekonoverse-rs
COPY --from=builder /workspace/target/release/nekonoverse-backend-rs /usr/local/bin/nekonoverse-backend-rs
# 依存クレートのライセンス通知 (`.github/workflows/license-audit.yml` が
# `backend/Cargo.lock` との乖離を検知する、`scripts/cargo-about.sh` で再生成)。
COPY THIRD-PARTY-LICENSES.html /usr/share/doc/nekonoverse-backend-rs/THIRD-PARTY-LICENSES.html
USER 853:853
ENTRYPOINT ["/usr/local/bin/nekonoverse-backend-rs"]
