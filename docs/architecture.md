# アーキテクチャ

## データモデル

```
actors (ローカル & リモート)
  ├── avatar_file_id → drive_files
  └── header_file_id → drive_files
  └── users (ローカルユーザーのみ: 認証情報 + RSA 秘密鍵)
       └── passkey_credentials (WebAuthn パスキー)
  └── notes (投稿)
       └── reactions (絵文字リアクション)
  └── followers (フォロー関係)

drive_files (メディアファイル: ユーザー所有 or サーバー所有)
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

## メディアストレージ

S3 互換ストレージ (nekono3s) を使用し、手動 SigV4 署名でファイルの読み書きを行う（boto3 不要）。

- **アップロード**: `POST /api/v1/media` → バックエンドが SigV4 署名付きで S3 に保存 → DriveFile レコード作成
- **配信**: `GET /media/{key}` → nginx が s3proxy-deliverer にプロキシ → ファイルシステムから直接配信（バックエンドを経由しない）
- **ドライブ**: ユーザーごとのファイル管理。`server_file=true` でサーバー所有ファイル（アイコン等）
- **制限**: 画像のみ (JPEG, PNG, GIF, WebP, AVIF)、最大 10MB
- **画像情報**: 純 Python で PNG/JPEG/GIF/WebP のサイズを抽出（Pillow 不要）

### メディア配信フロー

```
Client → nginx (or Cloudflared) → s3proxy-deliverer → ファイルシステム (nekono3sと共有)
```

- **s3proxy-deliverer** は nekono3s と同じストレージボリュームを読み取り専用で共有し、xattr メタデータ（Content-Type 等）を読んで認証なしでファイルを配信する
- nekono3s 側で `S3_XATTR_JCLOUDS_COMPAT=true` を設定し、jclouds 形式の xattr (`user.user.content-type`) を書き込む
- nginx は `/media/{key}` を `/nekonoverse/{key}` にリライトして s3proxy-deliverer に転送する

### 画像自動タグ付け (neko-vision)

neko-vision マイクロサービス (Ollama 連携) で画像にタグ・キャプションを自動付与する。

```
upload / fetch_remote_note → Valkey queue (neko_vision:queue)
                                ↓
worker (BRPOP) → neko-vision API (POST /tag) → Ollama (gemma3:4b)
                                ↓
                DB 更新 (vision_tags, vision_caption, vision_at)
                                ↓
                SSE publish (timeline:public / timeline:home)
```

- **ローカルファイル**: S3 から読み取り → base64 → neko-vision
- **リモート添付**: URL からダウンロード (SSRF 保護付き) → base64 → neko-vision
- **コンテキスト**: ノート本文 + リプライツリー (最大5件) をプロンプトに含めて精度向上
- **リトライ**: 失敗時は指数バックオフ (最大5回)、超過で dead letter queue に移動
- **メディアタイムライン**: `/media` で vision_tags / vision_caption を検索・表示に活用
