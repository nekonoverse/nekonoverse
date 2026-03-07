# API リファレンス

## 認証

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/accounts` | ユーザー登録 |
| `POST` | `/api/v1/auth/login` | ログイン |
| `POST` | `/api/v1/auth/logout` | ログアウト |
| `GET` | `/api/v1/accounts/verify_credentials` | 現在のユーザー情報 |
| `PATCH` | `/api/v1/accounts/update_credentials` | プロフィール更新 (表示名・アバター・自己紹介・誕生日・fields・猫モード・Bot・承認制・ディスカバリー) |
| `POST` | `/api/v1/auth/change_password` | パスワード変更 |

## パスキー (WebAuthn)

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/passkey/register/options` | 登録チャレンジ取得 |
| `POST` | `/api/v1/passkey/register/verify` | 登録検証・保存 |
| `POST` | `/api/v1/passkey/authenticate/options` | 認証チャレンジ取得 |
| `POST` | `/api/v1/passkey/authenticate/verify` | 認証検証・セッション作成 |
| `GET` | `/api/v1/passkey/credentials` | パスキー一覧 |
| `DELETE` | `/api/v1/passkey/credentials/{id}` | パスキー削除 |

## Mastodon 互換 API

### 投稿

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/statuses` | 投稿作成 |
| `GET` | `/api/v1/statuses/{id}` | 投稿取得 |
| `DELETE` | `/api/v1/statuses/{id}` | 投稿削除 |
| `POST` | `/api/v1/statuses/{id}/react/{emoji}` | リアクション追加 |
| `POST` | `/api/v1/statuses/{id}/unreact/{emoji}` | リアクション削除 |
| `POST` | `/api/v1/statuses/{id}/reblog` | ブースト |
| `POST` | `/api/v1/statuses/{id}/unreblog` | ブースト解除 |
| `POST` | `/api/v1/statuses/{id}/bookmark` | ブックマーク追加 |
| `POST` | `/api/v1/statuses/{id}/unbookmark` | ブックマーク解除 |
| `POST` | `/api/v1/statuses/{id}/pin` | ピン留め |
| `POST` | `/api/v1/statuses/{id}/unpin` | ピン留め解除 |

### タイムライン

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/timelines/public` | 公開タイムライン |
| `GET` | `/api/v1/timelines/home` | ホームタイムライン |

### アカウント

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/accounts/{id}` | アカウント情報 |
| `GET` | `/api/v1/accounts/{id}/statuses` | ユーザーの投稿一覧 |
| `GET` | `/api/v1/accounts/{id}/relationship` | フォロー関係 |
| `GET` | `/api/v1/accounts/lookup?acct=user` | アカウント照会 |
| `GET` | `/api/v1/accounts/search?q=query` | アカウント検索 (WebFinger 解決対応) |
| `POST` | `/api/v1/accounts/{id}/follow` | フォロー |
| `POST` | `/api/v1/accounts/{id}/unfollow` | フォロー解除 |
| `POST` | `/api/v1/accounts/{id}/block` | ブロック |
| `POST` | `/api/v1/accounts/{id}/unblock` | ブロック解除 |
| `POST` | `/api/v1/accounts/{id}/mute` | ミュート |
| `POST` | `/api/v1/accounts/{id}/unmute` | ミュート解除 |
| `POST` | `/api/v1/accounts/move` | アカウント移行 |

### 通知

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/notifications` | 通知一覧 |
| `POST` | `/api/v1/notifications/{id}/dismiss` | 通知を既読 |
| `POST` | `/api/v1/notifications/clear` | 全通知を消去 |

### ブックマーク

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/bookmarks` | ブックマーク一覧 |

### 投票

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/polls/{id}` | 投票情報取得 |
| `POST` | `/api/v1/polls/{id}/votes` | 投票する |

## OAuth 2.0

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/apps` | アプリ登録 |
| `GET` | `/oauth/authorize` | 認可 |
| `POST` | `/oauth/token` | トークン取得 |
| `POST` | `/oauth/revoke` | トークン失効 |

## ActivityPub

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

## メディア / ドライブ

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/media` | メディアアップロード (multipart) |
| `POST` | `/api/v2/media` | メディアアップロード v2 |
| `GET` | `/api/v1/media/{id}` | メディア情報取得 |
| `DELETE` | `/api/v1/media/{id}` | メディア削除 |
| `GET` | `/api/v1/drive/files` | ドライブファイル一覧 |
| `GET` | `/media/{key}` | メディアファイル配信 |

## 管理者

すべて管理者権限が必要。

### サーバー設定

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/admin/server-icon` | サーバーアイコン設定 |
| `GET` | `/api/v1/admin/settings` | サーバー設定取得 |
| `PATCH` | `/api/v1/admin/settings` | サーバー設定更新 |
| `GET` | `/api/v1/admin/stats` | サーバー統計 |

### ユーザー管理

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/admin/users` | ユーザー一覧 |
| `PATCH` | `/api/v1/admin/users/{id}/role` | ロール変更 |
| `POST` | `/api/v1/admin/users/{id}/suspend` | 凍結 |
| `POST` | `/api/v1/admin/users/{id}/unsuspend` | 凍結解除 |
| `POST` | `/api/v1/admin/users/{id}/silence` | サイレンス |
| `POST` | `/api/v1/admin/users/{id}/unsilence` | サイレンス解除 |

### ドメインブロック

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/admin/domain_blocks` | ドメインブロック一覧 |
| `POST` | `/api/v1/admin/domain_blocks` | ドメインブロック追加 |
| `DELETE` | `/api/v1/admin/domain_blocks/{domain}` | ドメインブロック解除 |

### レポート・モデレーション

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/admin/reports` | レポート一覧 (status: open/resolved/rejected) |
| `POST` | `/api/v1/admin/reports/{id}/resolve` | レポート対応済み |
| `POST` | `/api/v1/admin/reports/{id}/reject` | レポート却下 |
| `DELETE` | `/api/v1/admin/notes/{id}` | 投稿削除 |
| `POST` | `/api/v1/admin/notes/{id}/sensitive` | センシティブ指定 |
| `GET` | `/api/v1/admin/log` | モデレーションログ |

### カスタム絵文字

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/admin/emoji/list` | ローカル絵文字一覧 |
| `POST` | `/api/v1/admin/emoji/add` | 絵文字追加 |
| `PATCH` | `/api/v1/admin/emoji/{id}` | 絵文字更新 |
| `DELETE` | `/api/v1/admin/emoji/{id}` | 絵文字削除 |
| `GET` | `/api/v1/admin/emoji/export` | ZIP エクスポート |
| `POST` | `/api/v1/admin/emoji/import` | ZIP インポート |
| `GET` | `/api/v1/admin/emoji/remote` | リモート絵文字一覧 (domain, search, limit, offset) |
| `GET` | `/api/v1/admin/emoji/remote/domains` | リモート絵文字のドメイン一覧 |
| `POST` | `/api/v1/admin/emoji/import-remote/{id}` | リモート絵文字をローカルにインポート |

### サーバーファイル

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/admin/server-files` | サーバーファイル一覧 |
| `POST` | `/api/v1/admin/server-files` | サーバーファイルアップロード |
| `DELETE` | `/api/v1/admin/server-files/{id}` | サーバーファイル削除 |

## インスタンス情報

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/instance` | インスタンス情報 |
| `GET` | `/api/v1/health` | ヘルスチェック |
