# Nekonoverse

ActivityPub server with Misskey-compatible emoji reactions and Mastodon-compatible REST API.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12, FastAPI, SQLAlchemy 2 (async), Alembic |
| Frontend | SolidJS, TypeScript, Vite |
| Database | PostgreSQL 18 |
| Cache/Pub-Sub | Valkey (Redis-compatible) |
| Object Storage | nekono3s (S3-compatible) + s3proxy-deliverer |
| Reverse Proxy | Nginx |
| Network | Tailscale, Cloudflare Tunnel (optional) |
| E2E Testing | Playwright (Chromium + Firefox) |

## Project Structure

```
backend/
  app/
    main.py              # FastAPI app, router registration
    config.py            # Pydantic settings (env vars)
    dependencies.py      # DI: get_db, get_current_user, etc.
    models/              # SQLAlchemy ORM models (26 files)
    schemas/             # Pydantic request/response schemas
    services/            # Business logic (one service per domain, 24 files)
    api/
      auth.py            # /api/v1/auth/* (login, register, TOTP 2FA)
      admin.py           # /api/v1/admin/*
      media.py           # /api/v1/media
      invites.py         # /api/v1/invites
      oauth.py           # OAuth endpoints
      passkey.py         # WebAuthn/Passkey endpoints
      mastodon/          # Mastodon-compatible API
        statuses.py      # /api/v1/statuses/* (batch emoji cache, notes_to_responses)
        accounts.py      # /api/v1/accounts/*
        timelines.py     # /api/v1/timelines/*
        notifications.py # /api/v1/notifications
        bookmarks.py     # /api/v1/bookmarks
        polls.py         # /api/v1/polls
        streaming.py     # SSE via Valkey pub/sub
        media_proxy.py   # HMAC-signed media proxy
    activitypub/
      routes.py          # AP inbox/outbox, actor endpoints
      handlers/          # Activity type handlers (create, like, follow, announce, ...)
      renderer.py        # Model -> AP JSON-LD
      http_signature.py  # HTTP Signature sign/verify
      webfinger.py       # /.well-known/webfinger
      nodeinfo.py        # /.well-known/nodeinfo
    utils/               # Helpers (crypto, sanitize, emoji, media_proxy)
    worker/              # Background delivery worker
  alembic/versions/      # Sequential migrations (001_* ~ 016_*)
  tests/                 # pytest + pytest-asyncio (56 test files)
frontend/
  src/
    api/                 # HTTP client per resource (9 files)
    pages/               # Route components (13 pages)
    components/
      auth/              # LoginForm, RegisterForm
      layout/            # Navbar
      notes/             # NoteCard, NoteComposer, VisibilitySelector
      reactions/         # EmojiPicker, ReactionBar
      timeline/          # Timeline
      Breadcrumb.tsx, Emoji.tsx, ImageLightbox.tsx, ...
    stores/              # SolidJS reactive state (auth, theme, streaming, ...)
    i18n/                # Translations (ja, en, neko)
    styles/global.css    # Global stylesheet
tests/
  e2e/                   # Playwright E2E tests (13 spec files)
scripts/                 # Utility scripts (seed-million.py, rebuild.sh, ...)
```

## Development Commands

All services run in Docker. Never run npm/pip on the host directly.

```bash
# Start all services
docker compose up -d

# Backend
docker compose exec app alembic upgrade head          # Run migrations
docker compose exec app python -m pytest tests/ -v    # Run tests
docker compose exec app pip install <package>         # Install Python package

# Frontend
docker compose exec frontend npm install <package>    # Install npm package
# node_modules is an anonymous volume inside the container; host copy is stale

# Logs
docker compose logs -f app
docker compose logs -f frontend
```

### Docker Compose Files

| File | Purpose |
|------|---------|
| `docker-compose.yml.example` | Production template |
| `docker-compose.dev.yml.example` | Development template |
| `docker-compose.e2e.yml` | E2E testing environment |
| `docker-compose.federation.yml` | Federation testing (multi-instance) |
| `docker-compose.misskey-federation.yml` | Misskey interop testing |

## Testing

### Backend (pytest)
- `docker compose exec app python -m pytest tests/ -v`
- Test DB: `nekonoverse_test` (auto-created, see `tests/conftest.py`)
- `asyncio_mode = "auto"` — no `@pytest.mark.asyncio` needed
- Fixtures: `db`, `app_client`, `authed_client`, `test_user`, `mock_valkey`

### E2E (Playwright)
- `tests/e2e/` — Chromium + Firefox
- Covers: auth, timeline, composer, admin, profile, hashtag, MFM rendering, etc.
- CI runs via `.github/workflows/test.yml`

### Federation
- `docker-compose.federation.yml` — multi-instance federation test
- `docker-compose.misskey-federation.yml` — Misskey interop
- CI runs via `.github/workflows/federation-test.yml`

## Key Conventions

### Backend
- **Async everywhere**: All DB/HTTP operations use async/await
- **Service layer**: Business logic in `services/`, not in route handlers
- **Auth**: Session cookie (`nekonoverse_session`) → Valkey → User lookup. TOTP 2FA optional.
- **Batch queries**: Timeline APIs use `get_reaction_summaries()`, `notes_to_responses()`, `_build_emoji_cache()` to avoid N+1. Use `selectinload` for eager loading of relations (actor, attachments, renote_of, quoted_note, in_reply_to).
- **Media proxy**: Remote media URLs are HMAC-signed and served through `/api/v1/media/proxy`
- **Visibility**: Notes have `public`/`unlisted`/`followers`/`direct` mapped from AP `to`/`cc`
- **Federation**: HTTP Signatures for auth, JSON-LD for AP payloads
- **Linting**: ruff (E, F, I rules, line-length 100)

### Frontend
- **SolidJS**: Use `createSignal`/`createEffect`, not React hooks. Inside `<Switch>`/`<Match>`, use `createEffect` instead of `onMount` for data fetching (onMount may not fire).
- **Stores**: Global state in `stores/` (auth, theme, streaming, composer, followedUsers, instance)
- **API calls**: Thin wrappers in `src/api/`, return typed data
- **i18n**: `@solid-primitives/i18n` — 3 languages (ja, en, neko) in `src/i18n/dictionaries/`
- **Styling**: Global CSS in `styles/global.css`, class-based
- **Components**: Organized by domain (`notes/`, `reactions/`, `auth/`, `layout/`, `timeline/`)

### Database
- **Migrations**: Alembic, sequential naming (`001_*`, `002_*`, ..., currently up to `016_*`)
- **Models**: SQLAlchemy 2.0 `Mapped[]` type hints
- **IDs**: UUID primary keys

## Git Workflow

### Repositories

| Remote | Repository | Role |
|--------|-----------|------|
| `origin` | 各自のフォーク (例: `nananek/nekonoverse`) | 普段の作業はここで行う |
| `upstream` | `nekonoverse/nekonoverse` | 本体 — 完成したらここにマージ (PR or push) |

### Branches

- **`main`**: Stable releases only. Tagged with semver (`v0.5.0`, `v0.5.1`, ...).
- **`develop`**: Active development branch. Push here for `unstable` Docker images.
- Merge to main: `git merge --no-ff develop`
- Tag on main: `git tag v<version>`

### 作業開始前のルール

1. **Plan Issue を作成する** — 作業開始前に `nekonoverse/nekonoverse` にIssueを立てる (`gh issue create -R nekonoverse/nekonoverse`)。タイトルに `[Plan]` プレフィックスを付け、自分にアサインする。
2. **重複チェック** — Issue作成前に `gh issue list -R nekonoverse/nekonoverse -l plan` や検索で、同じ内容の既存Planが進行中でないか確認する。進行中の重複があればそちらに合流する。
3. **作業完了後** — `origin` (fork) に push → `upstream` に PR またはマージ。Plan Issue を閉じる。

### リリース手順

1. **バージョン番号を更新する** — 以下の3箇所を新しいバージョンに揃える:
   - `backend/app/__init__.py` → `__version__ = "X.Y.Z"` (nodeinfoはここから読み取る)
   - `backend/pyproject.toml` → `version = "X.Y.Z"`
   - `frontend/package.json` → `"version": "X.Y.Z"`
2. **develop にコミット・push**
3. **main にマージ**: `git checkout main && git merge --no-ff develop`
4. **タグを打つ**: `git tag vX.Y.Z && git push origin main --tags`

### Docker Image Tags (CI)
- `v*` tag push → `latest` + semver tags (`0.5.1`, `0.5`)
- `develop` push → `unstable` tag

## CI/CD

| Workflow | Trigger | Content |
|----------|---------|---------|
| `test.yml` | PR / push to develop | Backend tests, E2E tests (Playwright), frontend build |
| `federation-test.yml` | PR / push to develop | Multi-instance federation test |
| `docker-publish.yml` | Tag push (`v*`) / develop push | Docker image build & publish |
| `docs.yml` | Push to main | MkDocs documentation deploy |

## Environment Variables

Set in `.env` at project root:

| Variable | Description |
|----------|------------|
| `DB_PASSWORD` | PostgreSQL password |
| `DOMAIN` | Public domain (e.g. `example.com`) |
| `SECRET_KEY` | HMAC/session signing key + TOTP secret encryption |
| `FRONTEND_URL` | Frontend origin URL |
| `DEBUG` | Enable debug mode (`true`/`false`) |
| `S3_ACCESS_KEY_ID` | S3 storage key |
| `S3_SECRET_ACCESS_KEY` | S3 storage secret |
| `S3_BUCKET` | S3 bucket name |
| `CLOUDFLARE_TUNNEL_TOKEN` | Cloudflare tunnel token (optional) |
