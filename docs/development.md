# 開発環境

## 必要なもの

- Docker & Docker Compose

## セットアップ

```bash
git clone https://github.com/nananek/nekonoverse.git
cd nekonoverse

# 環境変数を設定
cat <<'EOF' > .env
DB_PASSWORD=dev-password
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

バックエンドはソースマウント + `--reload`、フロントエンドは Vite のホットリロードで動作します。

## 管理者ユーザーの作成

```bash
docker compose -f docker-compose.dev.yml exec -it app python -m app.cli create-admin
```

## コマンド一覧

### バックエンド

```bash
# マイグレーション実行
docker compose -f docker-compose.dev.yml exec app alembic upgrade head

# テスト実行
docker compose -f docker-compose.dev.yml exec app python -m pytest tests/ -v

# Python パッケージ追加
docker compose -f docker-compose.dev.yml exec app pip install <package>

# ログ
docker compose -f docker-compose.dev.yml logs -f app
```

### フロントエンド

```bash
# npm パッケージ追加
docker compose -f docker-compose.dev.yml exec frontend npm install <package>

# ログ
docker compose -f docker-compose.dev.yml logs -f frontend
```

!!! note "node_modules"
    `node_modules` はコンテナ内の匿名ボリュームで管理されています。ホスト側の `node_modules` は使われません。npm コマンドは必ず `docker compose exec frontend` 経由で実行してください。

## テスト

### ユニットテスト

```bash
docker compose -f docker-compose.dev.yml exec app python -m pytest tests/ -v
```

- テスト DB は `nekonoverse_test` として自動作成されます（`tests/conftest.py`）
- `asyncio_mode = "auto"` — `@pytest.mark.asyncio` デコレータ不要
- 主なフィクスチャ: `db`, `app_client`, `authed_client`, `test_user`, `mock_valkey`

### 連合 E2E テスト

2 つの nekonoverse インスタンスを立ち上げ、実際にアクティビティを交換するテスト。

```bash
docker compose -f docker-compose.federation.yml up -d --build --wait
docker compose -f docker-compose.federation.yml run --rm --no-deps test-runner
```

## Docker Compose 構成

| ファイル | 用途 |
|---------|------|
| `docker-compose.dev.yml.example` | 開発用テンプレート（ホットリロード、ソースマウント、ポート直接公開） |
| `docker-compose.yml.example` | 本番用テンプレート（nginx リバースプロキシ、ワーカー） |
| `docker-compose.cloudflared.yml.example` | Cloudflare Tunnel 用テンプレート |
| `docker-compose.federation.yml` | 連合 E2E テスト用 |

開発時は `.example` をコピーして使います。`docker-compose.yml` と `docker-compose.dev.yml` は `.gitignore` 対象です。

## Git ブランチ

| ブランチ | 用途 |
|---------|------|
| `main` | 安定リリース。タグ付き (`v0.5.0`, `v0.5.1`, ...) |
| `develop` | 開発ブランチ。push で `unstable` Docker イメージがビルドされる |

```bash
# develop で作業 → main にマージ → タグ
git checkout main
git merge --no-ff develop
git tag v<version>
git push origin main develop v<version>
```
