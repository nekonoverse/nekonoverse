## [v0.3.0](https://github.com/nananek/nekonoverse/releases/tag/v0.3.0) — 2026-03-07

### 変更

- **メディア配信を s3proxy-deliverer 経由に変更** — バックエンドの `serve_media` エンドポイントを廃止し、nginx から s3proxy-deliverer に直接プロキシすることでバックエンドの負荷を削減
- nekono3s に `S3_XATTR_JCLOUDS_COMPAT=true` を追加（s3proxy-deliverer が xattr メタデータを読むために必要）

### 追加

- **デプロイガイド** — Docker を使わない構成、Cloudflared (Cloudflare Tunnel) を使う構成のドキュメントを追加

---

## [v0.2.0](https://github.com/nananek/nekonoverse/releases/tag/v0.2.0) — 2026-03-07

### 追加

- **パスキー (WebAuthn)** — パスワードレス認証の登録・認証・管理 API
- **設定ページ** — `/settings` でパスキー管理・ログアウトが可能に
- **ログインフォーム** — パスキーでのログインボタンを追加
- **ドキュメントサイト** — MkDocs Material による GitHub Pages ドキュメント
- **テーマ切り替え** — ダーク・ライト・Novel の 3 テーマ + フォントサイズ調整
- **プロフィール管理** — 表示名の編集・パスワード変更
- **メディアドライブ** — S3 互換ストレージによるファイル管理 (Mastodon 互換メディア API)
- **アバターアップロード** — 設定ページからアバター画像を変更可能
- **サーバーアイコン** — 管理者がサーバーアイコンを設定可能 (`/api/v1/admin/server-icon`)
- **ナビゲーションバー** — ヘッダーにナビゲーションを追加
- **ユーザー名正規化** — ユーザー名を大文字小文字区別なくユニークに

### 修正

- `DeliveryQueue` → `DeliveryJob` のインポート名修正 (`models/__init__.py`)
- Federation テストの `--no-deps` 修正（Docker コンテナ再作成による IP キャッシュ問題）

---

## [v0.1.2](https://github.com/nananek/nekonoverse/releases/tag/v0.1.2) — 2026-03-03

### 追加

- **多言語 UI (i18n)** — 日本語・英語対応、ブラウザ言語自動検出、`localStorage` 永続化
- **GHCR ワークフロー** — タグ push 時に Docker イメージを GitHub Container Registry に自動ビルド・公開
- **Federation Test CI** — main push 時に連合 E2E テストを自動実行
- **Docker Compose テンプレート** — 開発用・本番用の `.example` ファイルを追加

---

## [v0.0.1](https://github.com/nananek/nekonoverse/releases/tag/v0.0.1) — 2026-03-03

### 初回リリース

- **ActivityPub** — Actor, Inbox, Outbox, WebFinger, NodeInfo 対応
- **Mastodon 互換 API** — 投稿・タイムライン・アカウント・フォロー・リアクション
- **絵文字リアクション** — Misskey 互換 (`Like` + `_misskey_reaction`) & Pleroma 互換 (`EmojiReact`)
- **OAuth 2.0** — Authorization Code + PKCE、Client Credentials
- **HTTP Signature** — RSA-SHA256 による署名・検証
- **配信キュー** — PostgreSQL + Valkey による非同期配信、指数バックオフでリトライ
- **ユニットテスト** — 237 テスト (30 ファイル)
- **連合 E2E テスト** — 27 テスト（2 インスタンス間の実通信）
- **管理 CLI** — `create-admin` コマンド
- **SolidJS フロントエンド** — ホーム・ログイン・登録ページ
