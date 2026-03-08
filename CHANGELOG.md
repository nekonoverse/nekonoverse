## [v0.5.4](https://github.com/nekonoverse/nekonoverse/releases/tag/v0.5.4) — 2026-03-08

### 追加

- **リモートカスタム絵文字のノート内表示** — リモートサーバーのカスタム絵文字をノート内で画像表示。ドメイン別の絵文字解決により、同一ショートコードでもリモート側の絵文字を優先表示し、ローカルにフォールバック
- **カスタム絵文字テスト** — sanitize、バッチ絵文字検索、note_to_response 絵文字解決のユニットテスト (14 テスト)

### 変更

- `sanitize_html()` で絵文字 `<img alt=":shortcode:">` をサニタイズ前に `:shortcode:` テキストに変換し保持
- `note_to_response()` を async 化、`emojis` フィールドで絵文字URLを返却 (Mastodon API 互換)
- フロントエンド `emojify()` ユーティリティ追加: DOM 内の `:shortcode:` を `<img>` に置換

### 修正

- **リモートメンションのローカル照会** — リモートユーザーのメンションクリック時に外部URLへ遷移する代わりに、ローカルの `/@user@domain` プロフィールページに遷移し WebFinger 照会を行うように変更
- **NoteCard メンションのルーター連携** — `innerHTML` で挿入されたメンションリンクが SolidJS Router をバイパスする問題を修正
- **プロフィールナビゲーションバグ修正** — プロフィールページ遷移時の不具合を修正
- **CLAUDE.md のtypo修正** — `nkonoverse` → `nekonoverse`

---

## [v0.5.2](https://github.com/nananek/nekonoverse/releases/tag/v0.5.2) — 2026-03-08

### 追加

- **Misskey プロフィール公開制限の連合対応** — `_misskey_requireSigninToViewContents`、`_misskey_makeNotesFollowersOnlyBefore`、`_misskey_makeNotesHiddenBefore` を尊重。未ログインユーザーにはプロフィール・ノートを制限表示
- **フォロワー/フォロー一覧ページ** — プロフィールからフォロワー・フォロー中ユーザーの一覧を表示、フォロー数カウント表示
- **フォロー申請の「承認待ち」UI** — relationship API に `requested` フィールド追加、フォロー申請中の状態表示と取り消し機能
- **リモートメンション完全ハンドル表示** — `@user@domain` 形式でリモートユーザーのメンションを正しく表示
- **メンション配信の修正** — WebFinger 解決によるリモートユーザーへのメンション配信対応
- **CI テストワークフロー** — バックエンドユニットテスト + フロントエンドビルドチェックを develop/main の push・PR で自動実行
- **Misskey 連合テスト** — Nekonoverse ↔ Misskey 間の HTTPS 連合テスト (30 テスト)
- **Block/Move ハンドラテスト** — Block・Move ActivityPub ハンドラのエッジケーステスト (11 テスト)

### 変更

- DB マイグレーション 013: `actors` テーブルに `require_signin_to_view`、`make_notes_followers_only_before`、`make_notes_hidden_before` を追加
- ActivityPub `render_actor` に Misskey 公開制限フィールドを出力
- `upsert_remote_actor` で Misskey 公開制限フィールドを取り込み
- 公開タイムライン・プロフィールノート一覧で日時ベースの公開制限フィルタを適用
- インスタンスバージョンを 0.5.2 に更新

### 修正

- CI: `pyproject.toml` ベースの依存管理に対応 (`pip install -e ".[dev]"`)
- CI: rollup ネイティブモジュール欠落を修正 (`npm install` に変更)
- テスト: SimpleNamespace モックに不足属性を追加、http/https スキーム不一致を修正
- テスト: S3 delete_file のパッチターゲット修正

---

## [v0.4.0](https://github.com/nananek/nekonoverse/releases/tag/v0.4.0) — 2026-03-08

### 追加

- **プロフィール設定** — 自己紹介・誕生日・プロフィール補足情報(fields)・猫モード・Bot フラグ・フォロー承認制・ディスカバリー掲載をプロフィールページからインライン編集可能に
- **リモート絵文字インポート** — 管理画面から連合でキャッシュされた他サーバーの絵文字を閲覧・ローカルにインポート (`/api/v1/admin/emoji/remote`, `/api/v1/admin/emoji/import-remote/{id}`)
- **ローカル絵文字フォールバック** — リアクション受信時、自サーバーに同じショートコードの絵文字がある場合はローカル版を使用
- **カスタム絵文字表示** — リアクションでカスタム絵文字を画像として表示 (`emoji_url` フィールド追加)
- **送信リアクションに絵文字タグ付与** — Like activity にカスタム絵文字の `tag` を含めて連合先が画像を取得できるように
- **ユーザー照会** — 検索ページで `user@example.com` 形式のリモートユーザーを WebFinger 解決、1件ヒット時は自動遷移

### 変更

- DB マイグレーション 012: `actors` テーブルに `birthday` (Date) と `is_bot` (Boolean) を追加
- `update_credentials` API を拡張: `summary`, `fields_attributes`, `birthday`, `is_cat`, `is_bot`, `locked`, `discoverable` パラメータ追加
- ActivityPub `render_actor` に `attachment` (PropertyValue) と `vcard:bday` を追加
- `upsert_remote_actor` でリモートアクターの `fields`, `birthday`, `is_bot`, `manually_approves_followers`, `discoverable` を更新に対応
- Settings ページからプロフィールタブを削除 (インライン編集に統合)
- 検索プレースホルダーを `user@example.com` 形式を示すように変更

---

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
