# コントリビューションガイド

Nekonoverseへの貢献に興味を持っていただきありがとうございます。このドキュメントでは、貢献の手順とルールを説明します。

## 目次

- [行動規範](#行動規範)
- [貢献の方法](#貢献の方法)
- [開発環境のセットアップ](#開発環境のセットアップ)
- [ブランチ戦略](#ブランチ戦略)
- [コーディング規約](#コーディング規約)
- [テスト](#テスト)
- [Pull Requestの作成](#pull-requestの作成)
- [翻訳の貢献](#翻訳の貢献)
- [セキュリティ脆弱性の報告](#セキュリティ脆弱性の報告)
- [ライセンス](#ライセンス)

## 行動規範

- 他のコントリビューターに対して敬意を持って接してください
- 建設的なフィードバックを心がけてください
- いいかんじ(TM)にやっていきましょう

## 貢献の方法

以下のような貢献を歓迎しています:

- **バグ報告** — Issueを作成してください
- **機能提案** — `[Plan]` プレフィックス付きのIssueを作成してください
- **コード貢献** — Pull Requestを送ってください
- **翻訳** — 新しい言語の追加や既存翻訳の改善
- **ドキュメント改善** — 誤字修正、説明の追加など

### Issueの作成

1. [既存のIssue](https://github.com/nekonoverse/nekonoverse/issues)を検索し、重複がないか確認してください
2. 機能提案の場合は、タイトルに `[Plan]` プレフィックスを付けてください
3. バグ報告には、再現手順・期待される動作・実際の動作を含めてください

## 開発環境のセットアップ

必要なものは **Docker & Docker Compose** のみです。

詳細なセットアップ手順は[開発環境ドキュメント](https://nekonoverse.github.io/nekonoverse/development/)を参照してください。

```bash
# リポジトリをフォーク & クローン
git clone https://github.com/<your-username>/nekonoverse.git
cd nekonoverse

# upstream を追加
git remote add upstream https://github.com/nekonoverse/nekonoverse.git

# 環境変数を設定
cat <<'EOF' > .env
DB_PASSWORD=dev-password
DOMAIN=localhost
SECRET_KEY=$(openssl rand -base64 32)
DEBUG=true
EOF

# 開発用 Compose ファイルをコピーして起動
cp docker-compose.dev.yml.example docker-compose.dev.yml
docker compose -f docker-compose.dev.yml up -d
```

## ブランチ戦略

| ブランチ | 用途 |
|---------|------|
| `main` | 安定リリース。タグ付き (`v0.5.0`, `v0.5.1`, ...) |
| `develop` | 開発ブランチ。PRのベースはここ |
| `feature/*` | 機能開発用の作業ブランチ |

### 作業の流れ

1. `upstream/develop` から最新を取り込む

   ```bash
   git fetch upstream
   git checkout develop
   git merge upstream/develop
   ```

2. 作業ブランチを作成する

   ```bash
   git checkout -b feature/your-feature-name
   ```

3. 変更をコミットし、フォークにpushする

   ```bash
   git push origin feature/your-feature-name
   ```

4. `nekonoverse/nekonoverse` の `develop` ブランチに向けてPull Requestを作成する

## コーディング規約

### バックエンド (Python)

- **リンター**: ruff (`E`, `F`, `I` ルール、行長100文字)
- **非同期**: DB/HTTP操作はすべて `async/await` を使用
- **サービス層**: ビジネスロジックは `services/` に配置し、ルートハンドラには書かない
- **N+1防止**: `selectinload` によるイーガーロード、バッチクエリを使用
- **型ヒント**: SQLAlchemy 2.0の `Mapped[]` を使用
- **テスト**: 新しいエンドポイントやサービス関数には対応するテストを追加

```bash
# リンター実行
docker compose -f docker-compose.dev.yml exec app ruff check app/
docker compose -f docker-compose.dev.yml exec app ruff format app/
```

### フロントエンド (SolidJS / TypeScript)

- **SolidJS**: `createSignal`/`createEffect` を使用（React hooksではない）
- **データ取得**: `<Switch>`/`<Match>` 内では `onMount` ではなく `createEffect` を使用
- **状態管理**: グローバルステートは `stores/` に配置
- **APIクライアント**: `src/api/` に薄いラッパーとして配置
- **スタイル**: `styles/global.css` でクラスベースのスタイリング
- **コンポーネント**: ドメイン別にディレクトリを分割 (`notes/`, `reactions/`, `auth/` 等)

### コメント・ドキュメント

- **コメント・docstring・JSDoc**: 日本語で記述
- コードの「なぜ」を説明するコメントを書く。「何をしているか」はコード自体で表現する
- 変数名・関数名・クラス名は英語（Python/TypeScriptの慣例に従う）
- ログメッセージは英語可（運用時の検索性を考慮）

## テスト

### ユニットテスト (pytest)

```bash
docker compose -f docker-compose.dev.yml exec app python -m pytest tests/ -v
```

- テストDBは `nekonoverse_test` として自動作成されます
- `asyncio_mode = "auto"` — `@pytest.mark.asyncio` は不要
- 主なフィクスチャ: `db`, `app_client`, `authed_client`, `test_user`, `mock_valkey`

### E2Eテスト (Playwright)

```bash
docker compose -f docker-compose.e2e.yml up -d --build --wait
docker compose -f docker-compose.e2e.yml run --rm playwright npx playwright test
```

- Chromium + Firefoxで実行
- テストファイルは `tests/e2e/` に配置

### 連合テスト

```bash
docker compose -f docker-compose.federation.yml up -d --build --wait
docker compose -f docker-compose.federation.yml run --rm --no-deps test-runner
```

PRを出す前に、少なくともユニットテストが通ることを確認してください。

## Pull Requestの作成

### PRの要件

- `develop` ブランチに向けて作成してください
- CIのテスト(ユニットテスト、E2E、フロントエンドビルド)がすべて通ること
- 新機能やバグ修正には対応するテストを含めること
- 既存のテストが壊れていないこと

### PRのフォーマット

```markdown
## 概要
変更内容の簡潔な説明

## 主な変更点
- 変更1
- 変更2

## テスト
- [ ] ユニットテスト通過
- [ ] 新規テスト追加（該当する場合）
- テスト実行方法: `docker compose -f docker-compose.dev.yml exec app python -m pytest tests/ -v`

## 関連Issue
Closes #<issue-number>
```

### データベースマイグレーション

DBスキーマを変更する場合:

1. Alembicマイグレーションファイルを作成する
2. ファイル名は連番 (`001_*`, `002_*`, ...) に従う
3. PRの説明にマイグレーション内容を記載する

## 翻訳の貢献

フロントエンドは日本語 (ja)、英語 (en)、ねこ語 (neko) の3言語に対応しています。

新しい言語の追加方法は[i18nドキュメント](https://nekonoverse.github.io/nekonoverse/i18n/)を参照してください。

基本的な手順:

1. `frontend/src/i18n/dictionaries/` に新しい辞書ファイルを作成
2. `frontend/src/i18n/index.tsx` に言語を追加
3. 型チェックにより、キーの過不足がコンパイル時に検出されます

## セキュリティ脆弱性の報告

セキュリティに関する脆弱性を発見した場合は、**公開Issueに詳細を書かないでください**。

代わりに、メンテナーに直接連絡してください。修正はPRのみで行い、PRのタイトルや本文にも攻撃手法の詳細は含めません。

## ライセンス

このプロジェクトは[いいかんじ(TM)ライセンス (IKL) v1.0 + MIT License](./LICENSE)の下で公開されています。

Pull Requestを送ることで、あなたの貢献がこのライセンスの下で公開されることに同意したものとみなされます。
