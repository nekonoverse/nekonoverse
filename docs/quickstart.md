# クイックスタート（本番）

## 必要なもの

- Docker & Docker Compose
- 独自ドメイン（ActivityPub の ID に使用されるため、**後から変更できません**）
- TLS 終端（nginx + Let's Encrypt、または Cloudflare Tunnel）

## 1. セットアップ

```bash
git clone https://github.com/nananek/nekonoverse.git
cd nekonoverse

# 環境変数を設定
cat <<'EOF' > .env
DB_PASSWORD=<強力なパスワード>
DOMAIN=your-domain.example
SECRET_KEY=$(openssl rand -base64 32)
DEBUG=false
FRONTEND_URL=https://your-domain.example
EOF

# Compose ファイルをコピー
cp docker-compose.yml.example docker-compose.yml
```

## 2. nginx 設定

TLS 終端 + リバースプロキシを設定します。`nginx/nginx.conf` を環境に合わせて編集してください。

Cloudflare Tunnel を使う場合は [デプロイガイド](deploy.md#cloudflared-cloudflare-tunnel-を使う場合) を参照。

## 3. 起動

```bash
docker compose up -d
```

## 4. 管理者ユーザーの作成

初回は CLI で管理者を作成します。対話型プロンプトで入力できます。

```bash
docker compose exec -it app python -m app.cli create-admin
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
docker compose exec app python -m app.cli create-admin \
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

いずれも引数なしで対話型、`--username` 等の引数付きで非対話型として動作します。

## 本番更新手順

GHCR のイメージを使っている場合:

```bash
docker compose pull
docker compose up -d
docker compose restart nginx
```

!!! important "nginx の再起動"
    `docker compose up -d` でバックエンドのコンテナが再作成されると内部 IP が変わる。nginx は起動時に upstream の DNS を解決してキャッシュするため、**app 更新後は必ず `docker compose restart nginx` を実行すること**。

### Docker イメージタグ

| タグ | 内容 | 用途 |
|------|------|------|
| `latest` | 最新リリースタグのビルド | 安定版を使いたい場合 |
| `0.5.1` | 特定バージョン | バージョン固定したい場合 |
| `0.5` | マイナーバージョン最新 | パッチ更新を自動で受けたい場合 |
| `unstable` | develop ブランチの最新ビルド | 最新の開発版を試したい場合 |

!!! warning "注意事項"
    - `DEBUG=false` で HTTPS モードになります。nginx または Cloudflare で TLS 終端してください
    - `DOMAIN` は ActivityPub ID に使用されるため、**運用開始後は変更できません**
    - 本番用 Compose は app/frontend を `expose` のみ（ポート直接公開なし）、nginx 経由でアクセスします
