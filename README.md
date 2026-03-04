# Nekonoverse

猫にやさしい ActivityPub サーバー。Misskey 互換の絵文字リアクションと Mastodon 互換の REST API を備えた、軽量な連合型 SNS。

**[ドキュメント](https://nananek.github.io/nekonoverse/)** | **[変更履歴](./CHANGELOG.md)** | **[ライセンス](./LICENSE)**

## 特徴

- **ActivityPub 準拠** — Misskey・Mastodon・Pleroma 等と相互に連合
- **絵文字リアクション** — Misskey 互換 & Pleroma 互換
- **Mastodon 互換 API** — 既存の Mastodon クライアントアプリから接続可能
- **パスキー (WebAuthn)** — パスワードレス認証に対応
- **OAuth 2.0** — Authorization Code + PKCE
- **多言語 UI** — 日本語・英語対応

## 技術スタック

Python 3.12 / FastAPI / SQLAlchemy 2 / SolidJS / Vite / PostgreSQL 17 / Valkey 8 / Docker Compose

## クイックスタート

```bash
git clone https://github.com/nananek/nekonoverse.git
cd nekonoverse

cat <<'EOF' > .env
DB_PASSWORD=your-db-password
DOMAIN=localhost
SECRET_KEY=$(openssl rand -base64 32)
DEBUG=true
EOF

cp docker-compose.dev.yml.example docker-compose.dev.yml
docker compose -f docker-compose.dev.yml up -d
```

- バックエンド API: http://localhost:8000
- フロントエンド: http://localhost:3000

詳細は[ドキュメント](https://nananek.github.io/nekonoverse/)を参照してください。

## ライセンス

[いいかんじ™ライセンス (IKL) v1.0 + MIT License](./LICENSE)
