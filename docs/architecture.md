# アーキテクチャ

## データモデル

```
actors (ローカル & リモート)
  └── users (ローカルユーザーのみ: 認証情報 + RSA 秘密鍵)
       └── passkey_credentials (WebAuthn パスキー)
  └── notes (投稿)
       └── reactions (絵文字リアクション)
  └── followers (フォロー関係)

delivery_queue (ActivityPub 配信ジョブ)
oauth_applications / oauth_tokens (OAuth 2.0)
```

- `actors` テーブルはローカル・リモート両方のユーザーを保持（`domain = NULL` でローカル）
- `users` テーブルはローカルユーザーの認証情報と RSA 秘密鍵のみ保持

## 配信キュー

1. アクティビティ発生時に `delivery_queue` テーブルへ INSERT
2. Valkey の `delivery:queue` キーに通知 (LPUSH)
3. ワーカーが BLPOP で待機 → ジョブ取得 → HTTP Signature 付きで POST
4. 失敗時は指数バックオフ (`60 * 2^attempts` 秒、最大 6 時間) でリトライ
5. 10 回失敗で `dead` ステータスに遷移

## 絵文字リアクション互換性

| 方向 | 形式 | 互換先 |
|------|------|--------|
| 送信 | `Like` + `_misskey_reaction` | Misskey, Mastodon |
| 受信 | `Like` (content / `_misskey_reaction`) | Misskey |
| 受信 | `EmojiReact` | Pleroma, Mastodon |

## 認証フロー

### セッション認証

1. `POST /api/v1/auth/login` でユーザー名・パスワードを送信
2. サーバーがセッション ID を生成し Valkey に保存
3. `nekonoverse_session` Cookie で返却
4. 以降のリクエストで Cookie を送信して認証

### パスキー (WebAuthn) 認証

1. `POST /api/v1/passkey/authenticate/options` でチャレンジを取得
2. ブラウザの WebAuthn API で署名を生成
3. `POST /api/v1/passkey/authenticate/verify` で検証
4. 成功時にセッション Cookie を発行

### OAuth 2.0

Authorization Code + PKCE フローに対応。サードパーティアプリからの認証に使用。
