# Nekonoverse

猫にやさしい ActivityPub サーバー。Misskey 互換の絵文字リアクションと Mastodon 互換の REST API を備えた、軽量な連合型 SNS。

## 特徴

- **ActivityPub 準拠** — Misskey・Mastodon・Pleroma 等と相互に連合
- **絵文字リアクション** — Misskey 互換 (`Like` + `_misskey_reaction`) & Pleroma 互換 (`EmojiReact`)
- **Mastodon 互換 API** — 既存の Mastodon クライアントアプリから接続可能
- **パスキー (WebAuthn)** — パスワードレス認証に対応、設定画面で管理
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

## プロジェクト構成

```
nekonoverse/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI エントリーポイント
│   │   ├── config.py               # 設定
│   │   ├── cli.py                  # 管理CLI
│   │   ├── models/                 # SQLAlchemy モデル
│   │   ├── api/                    # REST API エンドポイント
│   │   ├── activitypub/            # ActivityPub プロトコル
│   │   ├── services/               # ビジネスロジック
│   │   ├── worker/                 # バックグラウンドワーカー
│   │   └── utils/                  # ユーティリティ
│   ├── alembic/                    # DBマイグレーション
│   └── tests/                      # ユニットテスト
├── frontend/                       # SolidJS フロントエンド
│   └── src/
│       ├── pages/                  # ページコンポーネント
│       ├── components/             # UIコンポーネント
│       ├── stores/                 # 状態管理
│       ├── api/                    # API クライアント
│       └── i18n/                   # 多言語対応
└── tests/federation/               # 連合 E2E テスト
```

## ライセンス

[いいかんじ™ライセンス (IKL) v1.0 + MIT License](https://github.com/nananek/nekonoverse/blob/main/LICENSE)
