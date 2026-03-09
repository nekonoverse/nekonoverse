# Nekonoverse

猫にやさしい ActivityPub サーバー。Misskey 互換の絵文字リアクションと Mastodon 互換の REST API を備えた、軽量な連合型 SNS。

**[ドキュメント](https://nananek.github.io/nekonoverse/)** | **[変更履歴](./CHANGELOG.md)** | **[ライセンス](./LICENSE)**

## 特徴

### 連合・プロトコル
- **ActivityPub 準拠** — Misskey・Mastodon・Pleroma 等と相互に連合
- **絵文字リアクション** — Misskey 互換 & Pleroma 互換
- **Mastodon 互換 API** — 既存の Mastodon クライアントアプリから接続可能
- **Misskey 互換性** — プロフィール公開制限、猫モード、isCat、MFM レンダリング対応
- **OAuth 2.0** — Authorization Code + PKCE

### 投稿・タイムライン
- **ノート編集** — 編集履歴付きのノート編集、ActivityPub 連合対応
- **引用ノート** — 引用エンベッドのインライン表示
- **CW (Content Warning)** — スポイラーテキスト付きノートのトグル表示
- **ハッシュタグ** — ハッシュタグ抽出・タグタイムライン・連合対応
- **MFM レンダリング** — Misskey Flavored Markup の表示対応
- **スレッド表示** — 会話コンテキストの表示、リプライ対応
- **Visibility インジケーター** — unlisted/followers/direct のアイコン表示
- **リアルタイム更新** — SSE ストリーミングによるタイムライン・リアクションの即時反映

### 認証・セキュリティ
- **パスキー (WebAuthn)** — パスワードレス認証
- **TOTP 二要素認証** — Google Authenticator 等対応、リカバリーコード付き
- **招待コード** — 招待制登録の管理

### ユーザー機能
- **多言語 UI** — 日本語・英語・ねこ語対応
- **テーマ切り替え** — ダーク・ライト・Novel の 3 テーマ + フォントサイズ調整
- **プロフィール管理** — 表示名・自己紹介・誕生日・補足情報・猫モード・Bot フラグ等のインライン編集
- **フォロー管理** — フォロワー/フォロー一覧、承認待ち、ブロック・ミュート
- **リモート表示リンク** — リモートノート・ユーザーを元サーバーで表示するリンク
- **ユーザー照会** — @user@example.com 形式でリモートユーザーを WebFinger 解決
- **PWA 対応** — スワイプバックジェスチャー、バージョン更新通知
- **画像ライトボックス** — ズーム対応の画像ビューア

### 管理機能
- **管理ダッシュボード** — カテゴリカード形式の管理画面
- **ジョブキュー監視** — 配信キューの状態・リトライ管理
- **システムモニター** — CPU・メモリ・DB 接続状況の可視化
- **連合サーバー一覧** — 連合先サーバーの管理
- **カスタム絵文字管理** — ローカル・リモート絵文字の管理とインポート
- **メディアドライブ** — S3 互換ストレージによるファイル管理
- **サーバーアイコン** — 管理者がサーバーアイコンを設定可能
- **モデレーション** — ユーザーの凍結・サイレンス、通報管理

### 開発・運用
- **CI/CD** — ユニットテスト (56 ファイル)・E2E テスト (Playwright)・連合テスト (Neko↔Neko, Neko↔Misskey)
- **Docker Compose** — 開発・E2E・連合テスト・Misskey 連合テスト用の各構成

## 技術スタック

Python 3.12 / FastAPI / SQLAlchemy 2 / SolidJS / Vite / TypeScript / PostgreSQL 18 / Valkey 8 / Playwright / Docker Compose

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
