# API リファレンス

## 認証

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/accounts` | ユーザー登録 |
| `POST` | `/api/v1/auth/login` | ログイン |
| `POST` | `/api/v1/auth/logout` | ログアウト |
| `GET` | `/api/v1/accounts/verify_credentials` | 現在のユーザー情報 |
| `PATCH` | `/api/v1/accounts/update_credentials` | プロフィール更新 (表示名・アバター) |
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

| メソッド | パス | 説明 |
|---------|------|------|
| `POST` | `/api/v1/admin/server-icon` | サーバーアイコン設定 (管理者のみ) |

## インスタンス情報

| メソッド | パス | 説明 |
|---------|------|------|
| `GET` | `/api/v1/instance` | インスタンス情報 |
| `GET` | `/api/v1/health` | ヘルスチェック |
