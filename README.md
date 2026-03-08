# Nekonoverse

猫にやさしい ActivityPub サーバー。Misskey 互換の絵文字リアクションと Mastodon 互換の REST API を備えた、軽量な連合型 SNS。

**[ドキュメント](https://nananek.github.io/nekonoverse/)** | **[変更履歴](./CHANGELOG.md)** | **[ライセンス](./LICENSE)**

## 特徴

- **ActivityPub 準拠** — Misskey・Mastodon・Pleroma 等と相互に連合
- **絵文字リアクション** — Misskey 互換 & Pleroma 互換
- **Mastodon 互換 API** — 既存の Mastodon クライアントアプリから接続可能
- **Misskey 互換性** — プロフィール公開制限 (`requireSigninToViewContents` 等)、猫モード、isCat に対応
- **パスキー (WebAuthn)** — パスワードレス認証に対応
- **OAuth 2.0** — Authorization Code + PKCE
- **多言語 UI** — 日本語・英語・ねこ語対応
- **テーマ切り替え** — ダーク・ライト・Novel の 3 テーマ + フォントサイズ調整
- **プロフィール管理** — 表示名・自己紹介・誕生日・補足情報(fields)・猫モード・Bot フラグ等のインライン編集
- **フォロー管理** — フォロワー/フォロー一覧、承認待ち状態表示、ブロック・ミュート
- **リモート絵文字インポート** — 連合でキャッシュされた他サーバーの絵文字をローカルにインポート
- **ローカル絵文字フォールバック** — 他サーバーと同じ絵文字を持つ場合、自サーバーの絵文字でリアクション表示
- **ユーザー照会** — @user@example.com 形式でリモートユーザーを WebFinger 解決して閲覧
- **メディアドライブ** — S3 互換ストレージによるファイル管理、Mastodon 互換メディア API
- **サーバーアイコン** — 管理者がサーバーアイコンを設定可能
- **CI/CD** — ユニットテスト・連合テスト (Neko↔Neko, Neko↔Misskey) を GitHub Actions で自動実行

## 技術スタック

Python 3.12 / FastAPI / SQLAlchemy 2 / SolidJS / Vite / TypeScript / PostgreSQL 18 / Valkey 8 / Docker Compose

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
