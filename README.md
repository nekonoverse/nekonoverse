# Nekonoverse

猫にやさしい ActivityPub サーバー。Misskey 互換の絵文字リアクションと Mastodon 互換の REST API を備えた、軽量な連合型 SNS。

## 特徴

- **ActivityPub 準拠** — Misskey・Mastodon・Pleroma 等と相互に連合
- **絵文字リアクション** — Misskey 互換 (`Like` + `_misskey_reaction`) & Pleroma 互換 (`EmojiReact`)
- **Mastodon 互換 API** — 既存の Mastodon クライアントアプリから接続可能
- **OAuth 2.0** — Authorization Code + PKCE、Client Credentials に対応
- **HTTP Signature** — RSA-SHA256 による署名・検証
- **配信キュー** — PostgreSQL + Valkey による非同期配信、指数バックオフでリトライ
- **WebFinger / NodeInfo** — 標準的なサーバー間ディスカバリ
- **多言語 UI** — 日本語（デフォルト）・英語対応、ブラウザ言語自動検出

## 技術スタック

| レイヤー | 技術 |
|---------|------|
| バックエンド | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic |
| フロントエンド | SolidJS, Vite, TypeScript, @solid-primitives/i18n |
| データベース | PostgreSQL 17 |
| キャッシュ/セッション | Valkey 8 |
| インフラ | Docker Compose, GitHub Actions |

## クイックスタート

### 必要なもの

- Docker & Docker Compose

### 起動

```bash
git clone https://github.com/yourname/nekonoverse.git
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

### 管理者ユーザーの作成

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

## プロジェクト構成

```
nekonoverse/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI エントリーポイント
│   │   ├── config.py               # 設定
│   │   ├── cli.py                  # 管理CLI
│   │   ├── models/                 # SQLAlchemy モデル
│   │   │   ├── actor.py            #   Actor (ローカル/リモートユーザー)
│   │   │   ├── user.py             #   User (認証情報・秘密鍵)
│   │   │   ├── note.py             #   Note (投稿)
│   │   │   ├── reaction.py         #   Reaction (絵文字リアクション)
│   │   │   ├── follow.py           #   Follow (フォロー関係)
│   │   │   ├── delivery.py         #   DeliveryJob (配信キュー)
│   │   │   └── oauth.py            #   OAuth アプリ・トークン
│   │   ├── api/                    # REST API エンドポイント
│   │   │   ├── auth.py             #   認証 (登録/ログイン/ログアウト)
│   │   │   ├── oauth.py            #   OAuth 2.0
│   │   │   └── mastodon/           #   Mastodon 互換 API
│   │   │       ├── accounts.py     #     アカウント操作
│   │   │       ├── statuses.py     #     投稿・リアクション
│   │   │       └── timelines.py    #     タイムライン
│   │   ├── activitypub/            # ActivityPub プロトコル
│   │   │   ├── routes.py           #   Actor, Inbox, Outbox
│   │   │   ├── renderer.py         #   JSON-LD レンダリング
│   │   │   ├── http_signature.py   #   HTTP Signature 署名・検証
│   │   │   ├── webfinger.py        #   WebFinger
│   │   │   ├── nodeinfo.py         #   NodeInfo
│   │   │   └── handlers/           #   受信アクティビティの処理
│   │   ├── services/               # ビジネスロジック
│   │   ├── worker/                 # バックグラウンドワーカー
│   │   │   └── delivery_worker.py  #   配信キュー処理
│   │   └── utils/                  # ユーティリティ
│   ├── alembic/                    # DBマイグレーション
│   ├── tests/                      # ユニットテスト
│   └── pyproject.toml
├── frontend/                       # SolidJS フロントエンド
│   └── src/
│       ├── App.tsx                  # ルーター + I18nProvider
│       ├── i18n/                   # 多言語対応
│       │   ├── index.tsx           #   Provider + useI18n hook
│       │   └── dictionaries/       #   言語辞書
│       │       ├── ja.ts           #     日本語 (デフォルト)
│       │       └── en.ts           #     英語
│       ├── pages/                  # ページコンポーネント
│       ├── components/             # UIコンポーネント
│       ├── stores/                 # 状態管理
│       └── api/                    # API クライアント
├── tests/federation/               # 連合 E2E テスト
├── docker-compose.dev.yml.example  # 開発環境テンプレート
├── docker-compose.yml.example      # 本番環境テンプレート
└── docker-compose.federation.yml   # 連合テスト環境
```

## 多言語対応 (i18n)

フロントエンドは `@solid-primitives/i18n` による多言語対応を実装しています。

- **対応言語**: 日本語 (ja)、英語 (en)
- **デフォルト**: 日本語（ブラウザ言語で自動検出）
- **切替**: 右上のボタンで `JA` ↔ `EN` をトグル
- **永続化**: `localStorage` に保存、リロード後も保持

### 言語の追加方法

1. `frontend/src/i18n/dictionaries/` に新しい辞書ファイル（例: `ko.ts`）を作成
2. `frontend/src/i18n/index.tsx` の `dictionaries` と `locales` に追加
3. 型定義は `ja.ts` の `Dictionary` 型で保証されるため、キーの過不足がコンパイル時に検出されます

## API エンドポイント

### 認証

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/accounts` | ユーザー登録 |
| `POST` | `/api/v1/auth/login` | ログイン |
| `POST` | `/api/v1/auth/logout` | ログアウト |
| `GET` | `/api/v1/accounts/verify_credentials` | 現在のユーザー情報 |

### Mastodon 互換 API

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/statuses` | 投稿作成 |
| `GET` | `/api/v1/statuses/{id}` | 投稿取得 |
| `POST` | `/api/v1/statuses/{id}/react/{emoji}` | リアクション追加 |
| `POST` | `/api/v1/statuses/{id}/unreact/{emoji}` | リアクション削除 |
| `GET` | `/api/v1/timelines/public` | 公開タイムライン |
| `GET` | `/api/v1/timelines/home` | ホームタイムライン |
| `GET` | `/api/v1/accounts/{id}` | アカウント情報 |
| `GET` | `/api/v1/accounts/lookup?acct=user` | アカウント検索 |
| `POST` | `/api/v1/accounts/{id}/follow` | フォロー |
| `POST` | `/api/v1/accounts/{id}/unfollow` | フォロー解除 |

### OAuth 2.0

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/apps` | アプリ登録 |
| `GET` | `/oauth/authorize` | 認可 |
| `POST` | `/oauth/token` | トークン取得 |
| `POST` | `/oauth/revoke` | トークン失効 |

### ActivityPub

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/users/{username}` | Actor プロフィール |
| `POST` | `/users/{username}/inbox` | ユーザー Inbox |
| `POST` | `/inbox` | 共有 Inbox |
| `GET` | `/users/{username}/outbox` | Outbox |
| `GET` | `/users/{username}/followers` | フォロワー一覧 |
| `GET` | `/users/{username}/following` | フォロー中一覧 |
| `GET` | `/notes/{id}` | Note オブジェクト |
| `GET` | `/.well-known/webfinger` | WebFinger |
| `GET` | `/.well-known/nodeinfo` | NodeInfo ディスカバリ |
| `GET` | `/nodeinfo/2.0` | NodeInfo 2.0 |

## アーキテクチャ

### データモデル

```
actors (ローカル & リモート)
  └── users (ローカルユーザーのみ: 認証情報 + RSA 秘密鍵)
  └── notes (投稿)
       └── reactions (絵文字リアクション)
  └── followers (フォロー関係)

delivery_queue (ActivityPub 配信ジョブ)
oauth_applications / oauth_tokens (OAuth 2.0)
```

- `actors` テーブルはローカル・リモート両方のユーザーを保持（`domain = NULL` でローカル）
- `users` テーブルはローカルユーザーの認証情報と RSA 秘密鍵のみ保持

### 配信キュー

1. アクティビティ発生時に `delivery_queue` テーブルへ INSERT
2. Valkey の `delivery:queue` キーに通知 (LPUSH)
3. ワーカーが BLPOP で待機 → ジョブ取得 → HTTP Signature 付きで POST
4. 失敗時は指数バックオフ (`60 * 2^attempts` 秒、最大 6 時間) でリトライ
5. 10 回失敗で `dead` ステータスに遷移

### 絵文字リアクション互換性

| 方向 | 形式 | 互換先 |
|------|------|--------|
| 送信 | `Like` + `_misskey_reaction` | Misskey, Mastodon |
| 受信 | `Like` (content / `_misskey_reaction`) | Misskey |
| 受信 | `EmojiReact` | Pleroma, Mastodon |

## テスト

### ユニットテスト

```bash
# Docker 内で実行
docker compose -f docker-compose.dev.yml exec app python -m pytest tests/ -v
```

237 テスト (30 テストファイル) — API エンドポイント、サービス層、ActivityPub ハンドラー、WebFinger、NodeInfo、配信ワーカー、HTTP Signature、認証ミドルウェア、CLI、設定、ユーティリティをカバー。

### 連合 E2E テスト

2 つの nekonoverse インスタンスを立ち上げ、実際にアクティビティを交換するテスト。

```bash
docker compose -f docker-compose.federation.yml up -d --build --wait
docker compose -f docker-compose.federation.yml run --rm test-runner
```

27 テスト — WebFinger、Actor 取得、投稿の連合、フォロー、絵文字リアクション、タイムラインをカバー。

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

- `DEBUG=false` で HTTPS モードになります。nginx で TLS 終端してください
- `DOMAIN` に実際のドメイン名を設定してください（ActivityPub ID に使用されるため、後から変更できません）
- 本番用 Compose は app/frontend を `expose` のみ（ポート直接公開なし）、nginx 経由でアクセスします

## ライセンス

[いいかんじ™ライセンス (IKL) v1.0 + MIT License](./LICENSE)
