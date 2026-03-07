# クイックスタート

## 必要なもの

- Docker & Docker Compose

## 起動

```bash
git clone https://github.com/nananek/nekonoverse.git
cd nekonoverse

# 環境変数を設定
cat <<'EOF' > .env
DB_PASSWORD=your-db-password
DOMAIN=localhost
SECRET_KEY=$(openssl rand -base64 32)
DEBUG=true
EOF

# 開発用 Compose ファイルをコピー
cp docker-compose.dev.yml.example docker-compose.dev.yml

# 起動
docker compose -f docker-compose.dev.yml up -d
```

- バックエンド API: http://localhost:8000
- フロントエンド: http://localhost:3000

## 管理者ユーザーの作成

```bash
docker compose -f docker-compose.dev.yml exec app python -m app.cli create-admin \
  --username neko \
  --email neko@example.com \
  --password your-secure-password
```

## 設定

環境変数（`.env` ファイル）で設定します。

| 変数名 | 説明 | デフォルト |
|--------|------|-----------|
| `DB_PASSWORD` | PostgreSQL パスワード | (必須) |
| `DOMAIN` | サーバーのドメイン名 | `localhost` |
| `SECRET_KEY` | セッション署名用の秘密鍵 | (必須) |
| `DEBUG` | デバッグモード (`true` で HTTP、`false` で HTTPS) | `true` |
| `REGISTRATION_OPEN` | ユーザー登録を開放するか | `false` |
| `FRONTEND_URL` | フロントエンドの URL（パスキー検証で使用） | `http://localhost:3000` |
| `S3_ENDPOINT_URL` | S3 互換ストレージの URL | `http://nekono3s:9000` |
| `S3_ACCESS_KEY_ID` | S3 アクセスキー | `minioadmin` |
| `S3_SECRET_ACCESS_KEY` | S3 シークレットキー | `minioadmin` |
| `S3_BUCKET` | S3 バケット名 | `nekonoverse` |

## Docker Compose 構成

| ファイル | 用途 |
|---------|------|
| `docker-compose.dev.yml.example` | 開発用テンプレート（ホットリロード、ソースマウント、ポート直接公開） |
| `docker-compose.yml.example` | 本番用テンプレート（nginx リバースプロキシ、TLS、ワーカー 4 プロセス） |
| `docker-compose.federation.yml` | 連合 E2E テスト用 |

開発時は `.example` をコピーして使います。`docker-compose.yml` と `docker-compose.dev.yml` は `.gitignore` 対象です。

```bash
# 開発
cp docker-compose.dev.yml.example docker-compose.dev.yml
docker compose -f docker-compose.dev.yml up -d

# 本番
cp docker-compose.yml.example docker-compose.yml
# nginx.conf を用意し、TLS 証明書を設定
docker compose up -d
```

## 本番デプロイ

```bash
# Compose ファイルをコピー
cp docker-compose.yml.example docker-compose.yml

# .env の設定
cat <<'EOF' > .env
DB_PASSWORD=<強力なパスワード>
DOMAIN=your-domain.example
SECRET_KEY=<ランダムな文字列>
DEBUG=false
REGISTRATION_OPEN=false
EOF

# nginx.conf を用意 (TLS 終端 + リバースプロキシ)
# 起動
docker compose up -d
```

!!! warning "注意事項"
    - `DEBUG=false` で HTTPS モードになります。nginx で TLS 終端してください
    - `DOMAIN` に実際のドメイン名を設定してください（ActivityPub ID に使用されるため、後から変更できません）
    - 本番用 Compose は app/frontend を `expose` のみ（ポート直接公開なし）、nginx 経由でアクセスします

## テスト

### ユニットテスト

```bash
docker compose -f docker-compose.dev.yml exec app python -m pytest tests/ -v
```

262 テスト (31 テストファイル) — API エンドポイント（パスキー含む）、サービス層、ActivityPub ハンドラー、WebFinger、NodeInfo、配信ワーカー、HTTP Signature、認証ミドルウェア、CLI、設定、ユーティリティをカバー。

### 連合 E2E テスト

2 つの nekonoverse インスタンスを立ち上げ、実際にアクティビティを交換するテスト。

```bash
docker compose -f docker-compose.federation.yml up -d --build --wait
docker compose -f docker-compose.federation.yml run --rm --no-deps test-runner
```

27 テスト — WebFinger、Actor 取得、投稿の連合、フォロー、絵文字リアクション、タイムラインをカバー。
