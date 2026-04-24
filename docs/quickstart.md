# クイックスタート（本番）

## 必要なもの

- Docker & Docker Compose
- 独自ドメイン（ActivityPub の ID に使用されるため、**後から変更できません**）
- TLS 終端（nginx + Let's Encrypt、または Cloudflare Tunnel）

## 1. セットアップ

```bash
git clone https://github.com/nekonoverse/nekonoverse.git
cd nekonoverse

# 環境変数を設定
cat <<'EOF' > .env
DB_PASSWORD=<強力なパスワード>
DOMAIN=your-domain.example
SECRET_KEY=$(openssl rand -base64 32)
DEBUG=false
FRONTEND_URL=https://your-domain.example
S3_SECRET_ACCESS_KEY=<強力なパスワード>
EOF
```

## 2. nginx 設定

TLS 終端 + リバースプロキシを設定します。`nginx/prod.conf` を環境に合わせて編集してください。

Cloudflare Tunnel を使う場合は [デプロイガイド](deploy.md#cloudflared-cloudflare-tunnel-を使う場合) を参照。

## 3. 起動

```bash
# UDS 構成 (推奨)
docker compose -f docker-compose.prod.yml up -d
```

!!! note "TCP 構成"
    TCP 構成を使う場合は `cp docker-compose.yml.example docker-compose.yml` でコピーし、`docker compose up -d` で起動。詳細は [デプロイガイド](deploy.md) を参照。

## 4. 管理者ユーザーの作成

初回は CLI で管理者を作成します。対話型プロンプトで入力できます。

```bash
docker compose -f docker-compose.prod.yml exec -it app python -m app.cli create-admin
```

```
  Create Admin User

Username: neko
Email: neko@example.com
Password:
Password (confirm):
Display name [neko]: ねこ

Admin user created: neko (neko@example.com)
  role: admin
```

引数を直接指定することもできます:

```bash
docker compose -f docker-compose.prod.yml exec app python -m app.cli create-admin \
  --username neko \
  --email neko@example.com \
  --password your-secure-password
```

## 5. 初期設定

作成した管理者でログインし、管理画面（`/admin`）から以下を設定します:

- **サーバー名** — インスタンス名
- **サーバー説明** — インスタンスの説明文
- **サーバーアイコン** — ファビコン・PWA アイコン
- **ユーザー登録** — 一般ユーザーの登録を開放するかどうか

## 環境変数

`.env` ファイルで設定します。

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `DB_PASSWORD` | PostgreSQL パスワード | (必須) |
| `DOMAIN` | サーバーのドメイン名 | `localhost` |
| `SECRET_KEY` | セッション・HMAC 署名用の秘密鍵 | (必須) |
| `DEBUG` | デバッグモード (`false` で HTTPS) | `true` |
| `FRONTEND_URL` | フロントエンドの URL（パスキー検証で使用） | `http://localhost:3000` |
| `S3_ACCESS_KEY_ID` | S3 アクセスキー | `nekonoverse` |
| `S3_SECRET_ACCESS_KEY` | S3 シークレットキー | `changeme-s3` |
| `S3_BUCKET` | S3 バケット名 | `nekonoverse` |

## CLI コマンド

| コマンド | 説明 |
|---------|------|
| `python -m app.cli create-admin` | 管理者ユーザーの作成 |
| `python -m app.cli reset-password` | パスワードリセット |
| `python -m app.cli detect-focal-points` | 既存画像の顔検出一括実行 |

`create-admin` / `reset-password` は引数なしで対話型、`--username` 等の引数付きで非対話型として動作します。

`detect-focal-points` は `FACE_DETECT_URL` が設定されている環境で、フォーカルポイント未設定の画像に対して顔検出を一括実行します。`--concurrency` オプションで並列度を指定できます（デフォルト: 4）。

## 本番更新手順

GHCR のイメージを使っている場合:

```bash
# UDS 構成 (docker-compose.prod.yml) — nginx 再起動不要
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d

# TCP 構成 (docker-compose.yml) — nginx 再起動が必要
docker compose pull
docker compose up -d
docker compose restart nginx
```

!!! note "UDS 構成と TCP 構成"
    `docker-compose.prod.yml` では全サービス間通信を Unix Domain Socket で行うため、コンテナ再作成時に nginx の再起動が不要。TCP 構成 (`docker-compose.yml`) では内部 IP が変わるため `restart nginx` が必要。

### migration 042 適用時の delivery_queue bloat 解消 (一度だけ)

migration 042 適用後は定期 purge ワーカーが 1 時間ごとに 24h 超の `delivered` 行を削除し、`delivery_queue` の autovacuum も攻めた設定 (`scale_factor=0.05`) に変わります。ただし既存の bloat は手動で `VACUUM FULL` する必要があります（初回適用時のみ）。

```bash
# 現状確認: dead_ratio が 0.1 を超えていたら実施推奨
docker compose exec postgresql psql -U nekonoverse -d nekonoverse -c "
SELECT pg_size_pretty(pg_total_relation_size('delivery_queue')) AS size,
       n_dead_tup::float / NULLIF(n_live_tup,0) AS dead_ratio,
       n_live_tup AS live_rows
FROM pg_stat_user_tables WHERE relname='delivery_queue';
"

# 既存の delivered を purge してから VACUUM FULL（テーブルロックが走るので深夜帯推奨）
# VACUUM FULL はトランザクション内で実行できないため `-c` を分ける必要がある
docker compose exec postgresql psql -U nekonoverse -d nekonoverse \
  -c "DELETE FROM delivery_queue WHERE status='delivered' AND created_at < now() - interval '24 hours';" \
  -c "VACUUM FULL delivery_queue;"
```

### Docker イメージタグ

| タグ | 内容 | 用途 |
|------|------|------|
| `latest` | 最新リリースのビルド | 安定版を使いたい場合 |
| `20260311-1` | 特定リリース (yyyymmdd-x) | バージョン固定したい場合 |
| `unstable` | develop ブランチの最新ビルド | 最新の開発版を試したい場合 |

!!! warning "注意事項"
    - `DEBUG=false` で HTTPS モードになります。nginx または Cloudflare で TLS 終端してください
    - `DOMAIN` は ActivityPub ID に使用されるため、**運用開始後は変更できません**
    - UDS 構成ではサービス間を Unix Domain Socket で接続し、TCP ポートを外部に公開しません
