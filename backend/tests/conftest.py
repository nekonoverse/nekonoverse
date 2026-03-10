import os
import uuid
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

# Override settings BEFORE importing any app modules.
# Force test database — never use production DB even if DATABASE_URL is set.
_prod_url = os.environ.get("DATABASE_URL", "")
if _prod_url and "nekonoverse_test" not in _prod_url:
    # Rewrite to use test database
    os.environ["DATABASE_URL"] = _prod_url.rsplit("/", 1)[0] + "/nekonoverse_test"
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://nekonoverse:changeme@localhost:5432/nekonoverse_test")
os.environ.setdefault("VALKEY_URL", "valkey://localhost:6379/1")
os.environ["DOMAIN"] = "localhost"
os.environ["FRONTEND_URL"] = "http://localhost:3000"
os.environ.setdefault("SECRET_KEY", "test-secret-key")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("REGISTRATION_OPEN", "true")

# Import all models so relationships resolve
import app.models.actor  # noqa: F401
import app.models.bookmark  # noqa: F401
import app.models.custom_emoji  # noqa: F401
import app.models.delivery  # noqa: F401
import app.models.domain_block  # noqa: F401
import app.models.drive_file  # noqa: F401
import app.models.follow  # noqa: F401
import app.models.invitation_code  # noqa: F401
import app.models.moderation_log  # noqa: F401
import app.models.note  # noqa: F401
import app.models.note_attachment  # noqa: F401
import app.models.notification  # noqa: F401
import app.models.oauth  # noqa: F401
import app.models.pinned_note  # noqa: F401
import app.models.poll_vote  # noqa: F401
import app.models.passkey  # noqa: F401
import app.models.reaction  # noqa: F401
import app.models.report  # noqa: F401
import app.models.server_setting  # noqa: F401
import app.models.user  # noqa: F401
import app.models.user_block  # noqa: F401
import app.models.user_mute  # noqa: F401
from app.models.base import Base


_BASE_DATABASE_URL = os.environ["DATABASE_URL"]


def _get_worker_db_name(worker_id: str) -> str:
    """Return per-worker database name."""
    _, db_name = _BASE_DATABASE_URL.rsplit("/", 1)
    if worker_id == "master":
        return db_name
    return f"{db_name}_{worker_id}"


def _get_worker_db_url(worker_id: str) -> str:
    """Return per-worker database URL."""
    base = _BASE_DATABASE_URL.rsplit("/", 1)[0]
    return f"{base}/{_get_worker_db_name(worker_id)}"


def _sync_url(async_url: str) -> str:
    """Convert asyncpg URL to psycopg2."""
    return async_url.replace("postgresql+asyncpg://", "postgresql://")


def _create_worker_db(worker_id: str) -> None:
    """Create a per-worker database (sync, called before async engine)."""
    if worker_id == "master":
        return
    from sqlalchemy import create_engine, text

    admin_url = _sync_url(_BASE_DATABASE_URL)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    db_name = _get_worker_db_name(worker_id)
    with engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))
    engine.dispose()


def _drop_worker_db(worker_id: str) -> None:
    """Drop the per-worker database (sync, called after async engine dispose)."""
    if worker_id == "master":
        return
    from sqlalchemy import create_engine, text

    admin_url = _sync_url(_BASE_DATABASE_URL)
    engine = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    db_name = _get_worker_db_name(worker_id)
    with engine.connect() as conn:
        conn.execute(text(
            f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            f"WHERE datname = '{db_name}' AND pid <> pg_backend_pid()"
        ))
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}"'))
    engine.dispose()


@pytest.fixture(scope="session")
async def db_engine(worker_id):
    _create_worker_db(worker_id)
    db_url = _get_worker_db_url(worker_id)
    engine = create_async_engine(db_url, echo=False)
    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa.text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.execute(sa.text("DROP SCHEMA public CASCADE"))
        await conn.execute(sa.text("CREATE SCHEMA public"))
    await engine.dispose()
    _drop_worker_db(worker_id)


@pytest.fixture
async def db(db_engine) -> AsyncGenerator[AsyncSession, None]:
    async with db_engine.connect() as connection:
        trans = await connection.begin()
        session = AsyncSession(bind=connection, expire_on_commit=False)

        # Start a nested (savepoint) transaction so that application code's
        # commit() only commits the savepoint, not the outer transaction.
        nested = await connection.begin_nested()

        @event.listens_for(session.sync_session, "after_transaction_end")
        def restart_savepoint(sess, transaction):
            if transaction.nested and not transaction._parent.nested:
                sess.begin_nested()

        yield session

        await session.close()
        await trans.rollback()


@pytest.fixture
def mock_valkey():
    mock = AsyncMock()
    mock.get = AsyncMock(return_value=None)
    mock.set = AsyncMock(return_value=True)
    mock.lpush = AsyncMock(return_value=1)
    mock.delete = AsyncMock(return_value=1)
    mock.brpop = AsyncMock(return_value=None)
    with patch("app.valkey_client.valkey", mock):
        yield mock


@pytest.fixture
async def app_client(db, mock_valkey) -> AsyncGenerator[AsyncClient, None]:
    from app.dependencies import get_db
    from app.main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def test_user(db):
    from app.services.user_service import create_user
    return await create_user(db, "testuser", "test@example.com", "password1234", display_name="Test User")


@pytest.fixture
async def test_user_b(db):
    from app.services.user_service import create_user
    return await create_user(db, "testuser_b", "testb@example.com", "password1234", display_name="Test User B")


@pytest.fixture
async def authed_client(app_client, test_user, mock_valkey):
    session_id = "test-session-id"
    mock_valkey.get = AsyncMock(return_value=str(test_user.id))
    app_client.cookies.set("nekonoverse_session", session_id)
    return app_client


async def make_remote_actor(db, *, username="remote", domain="remote.example"):
    from app.models.actor import Actor
    from app.utils.crypto import generate_rsa_keypair
    _, public_pem = generate_rsa_keypair()
    actor = Actor(
        ap_id=f"http://{domain}/users/{username}",
        username=username,
        domain=domain,
        display_name=username.title(),
        inbox_url=f"http://{domain}/users/{username}/inbox",
        outbox_url=f"http://{domain}/users/{username}/outbox",
        shared_inbox_url=f"http://{domain}/inbox",
        followers_url=f"http://{domain}/users/{username}/followers",
        public_key_pem=public_pem,
    )
    db.add(actor)
    await db.flush()
    return actor


async def make_note(db, actor, *, content="Hello world", visibility="public", local=True):
    from app.models.note import Note
    from app.utils.sanitize import text_to_html
    note_id = uuid.uuid4()
    public = "https://www.w3.org/ns/activitystreams#Public"
    to_list = [public] if visibility == "public" else []
    cc_list = [actor.followers_url or ""] if visibility == "public" else []
    note = Note(
        id=note_id,
        ap_id=f"http://localhost/notes/{note_id}",
        actor_id=actor.id,
        content=text_to_html(content),
        source=content,
        visibility=visibility,
        to=to_list,
        cc=cc_list,
        local=local,
    )
    db.add(note)
    await db.flush()
    return note
