# デプロイガイド

## 標準構成 (Docker Compose)

[クイックスタート](quickstart.md) を参照。すべてのサービスが Docker Compose で管理される標準的な構成。

### TCP 構成 (`docker-compose.yml`)

```
Client → nginx → (TCP) → backend / frontend / s3proxy-deliverer
```

従来の構成。nginx が各サービスに TCP で接続する。`docker-compose.yml.example` をコピーして使用。

### UDS 構成 (`docker-compose.prod.yml`) — 推奨

```
Client → nginx → (UDS) → backend / s3proxy-deliverer
                → (volume) → frontend (静的ファイル)
         → (UDS) → PostgreSQL / Valkey
```

全サービス間通信を Unix Domain Socket で統一した本番推奨構成:

- **PostgreSQL / Valkey**: UDS 接続（TCP ポート無効化）
- **backend / s3proxy-deliverer**: nginx ↔ app 間を UDS
- **frontend**: ビルド済み静的ファイルを nginx が直接配信（Vite プロセス不要）
- **メリット**: コンテナ再作成時に nginx 再起動不要、ネットワーク攻撃面の削減、わずかなレイテンシ改善

```bash
cp .env.example .env  # 環境変数を設定
docker compose -f docker-compose.prod.yml up -d
```

## 本番更新手順

更新手順は [クイックスタート > 本番更新手順](quickstart.md#本番更新手順) を参照してください。

---

## Docker を使わない場合

Docker を使わずに各サービスを直接ホスト上で動かす構成。

### 必要なもの

| サービス | バージョン |
|---------|-----------|
| Python | 3.12+ |
| Node.js | 20+ |
| PostgreSQL | 17+ |
| Valkey (or Redis) | 8+ |
| nekono3s | latest |
| s3proxy-deliverer | latest |
| nginx (or Cloudflared) | - |

### nekono3s

nekono3s は S3 互換のオブジェクトストレージ。コンテナイメージからバイナリを取り出すか、ソースからビルドして使う。

```bash
# データディレクトリを作成
mkdir -p /var/lib/nekono3s

# 環境変数を設定して起動
export S3_ACCESS_KEY_ID=nekonoverse
export S3_SECRET_ACCESS_KEY=<強力なパスワード>
export S3_STORAGE_PATH=/var/lib/nekono3s
export S3_REGION=us-east-1
export S3_XATTR_JCLOUDS_COMPAT=true

# nekono3s を起動 (デフォルト: ポート 8080)
nekono3s
```

!!! important "xattr サポート"
    ストレージのファイルシステムが xattr をサポートしている必要がある（ext4, XFS, Btrfs 等）。`tmpfs` や一部の NFS では動作しない。

### s3proxy-deliverer

s3proxy-deliverer は nekono3s のデータディレクトリを読み取り専用で共有し、認証なしでファイルを配信する。

```bash
# nekono3s と同じデータディレクトリを指定
export STORAGE_ROOT=/var/lib/nekono3s

# s3proxy-deliverer を起動 (デフォルト: ポート 80)
s3proxy-deliverer
```

!!! note "ポートの変更"
    非 root で実行する場合、ポート 80 はバインドできない。`--port 8081` 等で変更し、nginx/Cloudflared のプロキシ先を合わせること。

### バックエンド

```bash
cd backend

# 依存関係をインストール
pip install -r requirements.txt

# 環境変数を設定
export DATABASE_URL=postgresql+asyncpg://nekonoverse:<password>@localhost:5432/nekonoverse
export VALKEY_URL=valkey://localhost:6379/0
export DOMAIN=your-domain.example
export SECRET_KEY=<ランダムな文字列>
export DEBUG=false
export S3_ENDPOINT_URL=http://localhost:8080
export S3_ACCESS_KEY_ID=nekonoverse
export S3_SECRET_ACCESS_KEY=<nekono3sと同じパスワード>
export S3_BUCKET=nekonoverse
export S3_REGION=us-east-1

# DBマイグレーション
alembic upgrade head

# アプリケーション起動
uvicorn app.main:app --host 127.0.0.1 --port 8000

# ワーカー起動 (別ターミナル)
python -m app.worker.main
```

### フロントエンド

```bash
cd frontend
npm install
npm run build

# 静的ファイルを nginx で配信するか、Vite プレビューサーバーを使う
npx vite preview --host 127.0.0.1 --port 3000
```

### nginx 設定

```nginx
upstream backend {
    server 127.0.0.1:8000;
}

upstream frontend {
    server 127.0.0.1:3000;
}

upstream s3proxy-deliverer {
    server 127.0.0.1:8081;  # s3proxy-deliverer のポート
}

server {
    listen 80;
    server_name your-domain.example;
    client_max_body_size 10M;

    # SSE streaming — バッファリング無効、長タイムアウト
    location /api/v1/streaming/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        chunked_transfer_encoding off;
    }

    # API routes
    location /api/ {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ActivityPub routes
    location /.well-known/ { proxy_pass http://backend; proxy_set_header Host $host; }
    location /users/       { proxy_pass http://backend; proxy_set_header Host $host; }
    location /inbox        { proxy_pass http://backend; proxy_set_header Host $host; }
    location /nodeinfo/    { proxy_pass http://backend; proxy_set_header Host $host; }
    location /oauth/       { proxy_pass http://backend; proxy_set_header Host $host; }
    location /manifest.webmanifest { proxy_pass http://backend; proxy_set_header Host $host; }

    # Notes: AP リクエストはバックエンドへ、ブラウザはフロントエンドへ
    location /notes/ {
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        if ($http_accept ~* "application/(activity\+json|ld\+json)") {
            proxy_pass http://backend;
            break;
        }
        proxy_pass http://frontend;
    }

    # Media files
    location /media/ {
        rewrite ^/media/(.*)$ /nekonoverse/$1 break;
        proxy_pass http://s3proxy-deliverer;
        proxy_set_header Host $host;
        proxy_hide_header x-amz-request-id;
        proxy_hide_header x-amz-id-2;
        add_header Cache-Control "public, max-age=86400, immutable";
        proxy_buffering on;
    }

    # Frontend
    location / {
        proxy_pass http://frontend;
        proxy_set_header Host $host;
    }
}
```

### systemd サービス例

各サービスを systemd で管理する場合の例:

```ini
# /etc/systemd/system/nekonoverse-backend.service
[Unit]
Description=Nekonoverse Backend
After=network.target postgresql.service valkey.service

[Service]
Type=exec
User=nekonoverse
WorkingDirectory=/opt/nekonoverse/backend
EnvironmentFile=/opt/nekonoverse/.env
ExecStart=/opt/nekonoverse/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

同様に `nekonoverse-worker.service`、`nekono3s.service`、`s3proxy-deliverer.service` を作成する。

---

## Cloudflared (Cloudflare Tunnel) を使う場合

nginx の代わりに Cloudflare Tunnel を使ってリバースプロキシを行う構成。TLS 終端やキャッシュを Cloudflare が担当する。

### メリット

- TLS 証明書の管理が不要（Cloudflare が自動管理）
- サーバーのポートを外部に公開する必要がない
- Cloudflare の CDN キャッシュが利用可能
- DDoS 対策が組み込まれている

### 構成図

```
Client → Cloudflare → cloudflared tunnel → backend / frontend / s3proxy-deliverer
```

### セットアップ

#### 1. Cloudflare Tunnel の作成

```bash
# cloudflared をインストール
# https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

# ログインしてトンネルを作成
cloudflared tunnel login
cloudflared tunnel create nekonoverse
```

#### 2. 設定ファイル

```yaml
# ~/.cloudflared/config.yml
tunnel: <tunnel-id>
credentials-file: ~/.cloudflared/<tunnel-id>.json

ingress:
  # API routes
  - hostname: your-domain.example
    path: /api/.*
    service: http://localhost:8000

  # ActivityPub routes
  - hostname: your-domain.example
    path: /.well-known/.*
    service: http://localhost:8000

  - hostname: your-domain.example
    path: /users/.*
    service: http://localhost:8000

  - hostname: your-domain.example
    path: /notes/.*
    service: http://localhost:8000

  - hostname: your-domain.example
    path: /inbox
    service: http://localhost:8000

  - hostname: your-domain.example
    path: /nodeinfo/.*
    service: http://localhost:8000

  - hostname: your-domain.example
    path: /oauth/.*
    service: http://localhost:8000

  - hostname: your-domain.example
    path: /manifest.webmanifest
    service: http://localhost:8000

  # Media files -> s3proxy-deliverer
  - hostname: your-domain.example
    path: /media/.*
    service: http://localhost:8081
    originRequest:
      httpHostHeader: your-domain.example

  # Everything else -> frontend
  - hostname: your-domain.example
    service: http://localhost:3000

  - service: http_status:404
```

!!! warning "メディアの URL リライト"
    Cloudflared は nginx のような `rewrite` をサポートしていない。`/media/{key}` → `/nekonoverse/{key}` のリライトが必要なため、s3proxy-deliverer の前段に軽量なリバースプロキシを挟むか、以下のいずれかの方法で対応する。

#### メディア URL リライトの対応方法

Cloudflared にはパスの書き換え機能がないため、`/media/` → `/nekonoverse/` のリライトに別途対応が必要。

**方法 A: Cloudflare Transform Rules (推奨)**

Cloudflare ダッシュボードの **Rules > Transform Rules > Rewrite URL** で設定:

- **条件**: `URI Path` starts with `/media/`
- **書き換え**: Dynamic — `concat("/nekonoverse", substring(http.request.uri.path, 6))`

この方法では Cloudflare のエッジでリライトが行われるため、追加のプロキシが不要。

**方法 B: Caddy をローカルリバースプロキシとして使う**

s3proxy-deliverer の前段に Caddy を置いてリライトを行う:

```
# Caddyfile
:8082 {
    handle /media/* {
        uri strip_prefix /media
        rewrite * /nekonoverse{uri}
        reverse_proxy localhost:8081
    }
}
```

Cloudflared の ingress で `/media/.*` のサービスを `http://localhost:8082` に変更する。

#### 3. DNS 設定

```bash
cloudflared tunnel route dns nekonoverse your-domain.example
```

#### 4. 起動

```bash
cloudflared tunnel run nekonoverse
```

#### Docker Compose で使う場合

`docker-compose.yml.example` の末尾にコメントアウトされた `cloudflared` サービスがあります。nginx サービスを削除（またはコメントアウト）し、cloudflared のコメントを外して使います。

Cloudflare Zero Trust ダッシュボードの **Networks > Tunnels** でトンネルを作成し、Public Hostname のルーティングを設定する。`CLOUDFLARE_TUNNEL_TOKEN` は `.env` に記載する。

!!! note "環境変数"
    Cloudflared を使う場合、バックエンドの `DEBUG=false` を設定すること。Cloudflare が HTTPS を終端し `X-Forwarded-Proto: https` をセットするため、バックエンドは HTTPS 前提で動作する。

---

## メール設定 (SMTP)

メール認証とパスワードリセット機能を有効にするには、SMTP サーバーの設定が必要。未設定の場合、メール機能は無効化され、既存の動作に影響はない。

### 環境変数

`.env` に追加:

```bash
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
SMTP_PASSWORD=re_xxxxxxxxxxxx
SMTP_FROM=noreply@yourdomain.com
SMTP_SECURITY=ssl
```

| 変数 | 説明 | デフォルト |
|------|------|-----------|
| `SMTP_HOST` | SMTP サーバーのホスト名 | (未設定=メール無効) |
| `SMTP_PORT` | ポート番号 | `587` |
| `SMTP_USER` | 認証ユーザー名 | — |
| `SMTP_PASSWORD` | 認証パスワードまたは API キー | — |
| `SMTP_FROM` | 送信元メールアドレス | `noreply@{DOMAIN}` |
| `SMTP_SECURITY` | 接続方式 | `starttls` |

### SMTP_SECURITY の選択

| 値 | ポート | 説明 | 対応サービス例 |
|----|--------|------|---------------|
| `starttls` | 587 | 平文接続後に STARTTLS でTLS昇格 | Gmail, Mailgun, SendGrid |
| `ssl` | 465 | 接続時からTLS (暗黙TLS/SMTPS) | Resend, Amazon SES |
| `none` | 25 | 暗号化なし (非推奨) | ローカル開発用 |

### 主要サービスの設定例

**Resend**:

```bash
SMTP_HOST=smtp.resend.com
SMTP_PORT=465
SMTP_USER=resend
SMTP_PASSWORD=re_xxxxxxxxxxxx
SMTP_FROM=noreply@yourdomain.com
SMTP_SECURITY=ssl
```

**Gmail (アプリパスワード)**:

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=you@gmail.com
SMTP_PASSWORD=xxxx-xxxx-xxxx-xxxx
SMTP_FROM=you@gmail.com
SMTP_SECURITY=starttls
```

### 動作

- **メール認証**: ユーザー登録時に認証メールを自動送信。未認証でもログイン・投稿は可能（Mastodon互換）。設定画面に認証状態を表示
- **パスワードリセット**: ログイン画面の「パスワードを忘れた場合」からリセットメールを送信
- **レート制限**: 同一ユーザーへの再送信は5分間隔に制限
- **メールキュー**: Valkey ベースの非同期キュー。最大5回リトライ、失敗はデッドレターキューへ

---

## Cloudflare Turnstile CAPTCHA

登録フォームに [Cloudflare Turnstile](https://developers.cloudflare.com/turnstile/) の CAPTCHA を追加できる。未設定時は CAPTCHA なしで動作する。

### セットアップ

1. [Cloudflare ダッシュボード](https://dash.cloudflare.com/) → **Turnstile** → **サイトを追加**
2. サイトのドメインを登録し、**Site Key** と **Secret Key** を取得
3. `.env` に追加:

```bash
TURNSTILE_SITE_KEY=0x...
TURNSTILE_SECRET_KEY=0x...
```

4. コンテナを再起動すれば登録フォームに CAPTCHA が表示される

---

## 顔検出サーバーを別マシンに分離する

[`face-detect/`](https://github.com/nekonoverse/face-detect)（git submodule）は顔検出マイクロサービスで、アップロードされた画像から顔の位置を検出し、フォーカルポイントを自動設定する。GPU マシンに分離することで、メインサーバーの負荷を分散できる。

検出は2段階で行われる（`DETECTION_MODE` で変更可能）:

1. **アニメ顔検出** (`deepghs/anime_face_detection` YOLO ONNX, GPU) — F1 0.97、VRAM ~50MB
2. **実写顔検出** (MTCNN, PyTorch, GPU) — アニメ顔が見つからない場合のフォールバック、VRAM ~200MB

| モード | 環境変数 `DETECTION_MODE` | 動作 | VRAM |
|--------|--------------------------|------|------|
| 自動 (デフォルト) | `auto` | アニメ→実写フォールバック | ~250MB |
| アニメのみ | `anime` | アニメ顔のみ検出 | ~50MB |
| 実写のみ | `real` | 実写顔のみ検出 | ~200MB |

!!! note "オプション機能"
    顔検出は `FACE_DETECT_URL` が未設定なら完全にスキップされる。サービスがダウンしていてもアップロードは正常に動作する（silent fail）。ユーザーはフロントエンドの FocalPointPicker から手動設定も可能。

### 構成図

```
Client → メインサーバー (backend) → GPU サーバー (face-detect)
                                     POST /object-detection
```

### GPU サーバー側のセットアップ

#### 直接実行

```bash
# face-detect/ ディレクトリをコピー
scp -r face-detect/ gpu-server:/opt/face-detect/

# GPU マシンで起動
cd /opt/face-detect
pip install -r requirements.txt   # torch, facenet-pytorch, onnxruntime-gpu, huggingface-hub, etc.

# 検出モードを指定して起動 (デフォルト: auto)
DETECTION_MODE=auto uvicorn main:app --host 0.0.0.0 --port 8100

# アニメのみモード (MTCNNをロードしない、VRAM節約)
DETECTION_MODE=anime uvicorn main:app --host 0.0.0.0 --port 8100
```

#### Docker

```dockerfile
FROM pytorch/pytorch:2.x-cuda12.x-runtime
COPY . /app
WORKDIR /app
RUN pip install -r requirements.txt
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8100"]
```

#### systemd サービス例

```ini
# /etc/systemd/system/face-detect.service
[Unit]
Description=Nekonoverse Face Detection
After=network.target

[Service]
Type=exec
User=nekonoverse
WorkingDirectory=/opt/face-detect
Environment=DETECTION_MODE=auto
ExecStart=/opt/face-detect/.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8100
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### メインサーバー側の設定

`.env` に追加:

```bash
FACE_DETECT_URL=http://<GPUマシンのIP>:8100
```

Docker Compose の場合は `docker-compose.yml` の `app` サービスの `environment` に追加する。

### ネットワーク

| 方式 | 設定例 | 備考 |
|------|--------|------|
| Tailscale (推奨) | `http://100.x.x.x:8100` | 設定不要で暗号化 |
| VPN / プライベートネットワーク | `http://192.168.x.x:8100` | ファイアウォールで 8100 を制限 |

!!! warning "セキュリティ"
    顔検出 API は認証なしのため、公開ネットワークに露出させないこと。Tailscale やファイアウォールでメインサーバーからのアクセスのみ許可する。

### 動作確認

```bash
# GPU マシンのヘルスチェック
curl http://<GPU_IP>:8100/health
# → {"status":"ok","device":"cuda","detection_mode":"auto","models":{"anime":true,"real":true}}

# メインサーバーからの疎通確認
curl http://<GPU_IP>:8100/health
```

### API 仕様

| エンドポイント | メソッド | 説明 |
|---------------|---------|------|
| `/health` | GET | ヘルスチェック。`models` でアニメ/実写の有効状況を返す |
| `/object-detection` | POST | 顔検出（アニメ優先→実写フォールバック）。HF Inference API 互換 |

レスポンス例 (`/object-detection`):

```json
[
  {
    "label": "anime_face",
    "score": 0.8,
    "box": { "xmin": 30, "ymin": 20, "xmax": 70, "ymax": 60 }
  }
]
```

`label` は `anime_face`（アニメ検出）または `face`（実写検出）。バックエンドはバウンディングボックスの中心座標を正規化 `[-1, 1]` のフォーカルポイントに変換して `drive_files.focal_x` / `focal_y` に保存する（`label` は参照しない）。
