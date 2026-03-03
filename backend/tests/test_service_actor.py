from datetime import datetime, timezone

from tests.conftest import make_remote_actor


async def test_get_actor_by_ap_id(db):
    from app.services.actor_service import get_actor_by_ap_id
    actor = await make_remote_actor(db)
    found = await get_actor_by_ap_id(db, actor.ap_id)
    assert found is not None
    assert found.id == actor.id


async def test_get_actor_by_ap_id_not_found(db):
    from app.services.actor_service import get_actor_by_ap_id
    found = await get_actor_by_ap_id(db, "http://nonexistent.example/users/nobody")
    assert found is None


async def test_get_actor_by_username_local(db, test_user):
    from app.services.actor_service import get_actor_by_username
    found = await get_actor_by_username(db, "testuser", domain=None)
    assert found is not None
    assert found.username == "testuser"


async def test_get_actor_by_username_remote(db):
    from app.services.actor_service import get_actor_by_username
    await make_remote_actor(db, username="bob", domain="other.example")
    found = await get_actor_by_username(db, "bob", domain="other.example")
    assert found is not None


async def test_upsert_remote_actor_creates(db):
    from app.services.actor_service import upsert_remote_actor
    data = {
        "id": "http://new.example/users/charlie",
        "type": "Person",
        "preferredUsername": "charlie",
        "name": "Charlie",
        "inbox": "http://new.example/users/charlie/inbox",
        "outbox": "http://new.example/users/charlie/outbox",
        "publicKey": {"id": "key-id", "publicKeyPem": "PEM_DATA"},
        "endpoints": {"sharedInbox": "http://new.example/inbox"},
    }
    actor = await upsert_remote_actor(db, data)
    assert actor is not None
    assert actor.username == "charlie"
    assert actor.domain == "new.example"


async def test_upsert_remote_actor_updates(db):
    from app.services.actor_service import upsert_remote_actor
    actor = await make_remote_actor(db, username="delta", domain="upd.example")
    data = {
        "id": actor.ap_id,
        "type": "Person",
        "preferredUsername": "delta",
        "name": "Delta Updated",
        "inbox": actor.inbox_url,
        "publicKey": {"publicKeyPem": actor.public_key_pem},
    }
    updated = await upsert_remote_actor(db, data)
    assert updated.display_name == "Delta Updated"


async def test_upsert_remote_actor_no_id(db):
    from app.services.actor_service import upsert_remote_actor
    result = await upsert_remote_actor(db, {"type": "Person"})
    assert result is None


async def test_upsert_remote_actor_no_username(db):
    from app.services.actor_service import upsert_remote_actor
    result = await upsert_remote_actor(db, {"id": "http://x.example/users/x"})
    assert result is None


async def test_upsert_remote_actor_icon_dict(db):
    from app.services.actor_service import upsert_remote_actor
    data = {
        "id": "http://icon.example/users/iconuser",
        "preferredUsername": "iconuser",
        "inbox": "http://icon.example/users/iconuser/inbox",
        "publicKey": {"publicKeyPem": "PEM"},
        "icon": {"type": "Image", "url": "http://icon.example/avatar.png"},
    }
    actor = await upsert_remote_actor(db, data)
    assert actor.avatar_url == "http://icon.example/avatar.png"


async def test_fetch_remote_actor_uses_cache(db):
    from app.services.actor_service import fetch_remote_actor
    actor = await make_remote_actor(db)
    actor.last_fetched_at = datetime.now(timezone.utc)
    await db.flush()
    result = await fetch_remote_actor(db, actor.ap_id)
    assert result is not None
    assert result.id == actor.id
