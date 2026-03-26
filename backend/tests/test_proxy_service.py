"""Tests for the system.proxy account and proxy subscription service."""

import uuid
from unittest.mock import AsyncMock, patch

from app.models.actor import Actor
from app.models.follow import Follow
from app.services.proxy_service import (
    get_system_actor_ids,
    get_proxy_account,
    has_real_local_follower,
    is_proxy_subscribed,
    proxy_subscribe,
    proxy_unsubscribe,
)
from app.services.system_account_service import (
    ensure_system_account,
    ensure_system_accounts,
    get_proxy_actor,
)

# -- system.proxy アカウント作成 --


async def test_ensure_system_accounts_creates_proxy(db):
    """ensure_system_accounts で system.proxy が自動作成される"""
    await ensure_system_accounts(db)
    user = await get_proxy_actor(db)
    assert user is not None
    assert user.is_system is True
    assert user.actor.username == "system.proxy"
    assert user.actor.type == "Application"
    assert user.actor.is_bot is True
    assert user.actor.discoverable is False


async def test_proxy_account_has_correct_email(db):
    user = await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    assert user.email == "system.proxy@system.internal"


async def test_proxy_account_has_keypair(db):
    user = await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    assert "BEGIN PRIVATE KEY" in user.private_key_pem
    assert "BEGIN PUBLIC KEY" in user.actor.public_key_pem


async def test_get_proxy_account_wrapper(db):
    """get_proxy_account は get_proxy_actor のラッパー"""
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    user = await get_proxy_account(db)
    assert user is not None
    assert user.actor.username == "system.proxy"


# -- proxy_subscribe --


def _make_remote_actor(domain="remote.example.com", username="remoteuser"):
    """テスト用のリモートアクターを作成"""
    actor_id = uuid.uuid4()
    return Actor(
        id=actor_id,
        ap_id=f"https://{domain}/users/{username}",
        type="Person",
        username=username,
        domain=domain,
        display_name=username,
        inbox_url=f"https://{domain}/users/{username}/inbox",
        outbox_url=f"https://{domain}/users/{username}/outbox",
        shared_inbox_url=f"https://{domain}/inbox",
        followers_url=f"https://{domain}/users/{username}/followers",
        following_url=f"https://{domain}/users/{username}/following",
        public_key_pem="-----BEGIN PUBLIC KEY-----\nMIIBIjANB...\n-----END PUBLIC KEY-----",
    )


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_proxy_subscribe_follows_remote_actor(mock_delivery, db):
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    follow = await proxy_subscribe(db, remote)
    assert follow is not None
    assert follow.accepted is False

    proxy_user = await get_proxy_actor(db)
    assert follow.follower_id == proxy_user.actor.id
    assert follow.following_id == remote.id

    # Follow Activity が配送キューに入ることを確認
    mock_delivery.assert_called_once()


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_proxy_subscribe_idempotent(mock_delivery, db):
    """同じアクターへの二重購読は既存のFollowを返す"""
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    follow1 = await proxy_subscribe(db, remote)
    follow2 = await proxy_subscribe(db, remote)
    assert follow1.id == follow2.id
    # 2回目は配送しない
    assert mock_delivery.call_count == 1


async def test_proxy_subscribe_rejects_local_actor(db):
    """ローカルアクターへのproxy購読はNoneを返す"""
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    local = Actor(
        id=uuid.uuid4(),
        ap_id="http://localhost/users/localuser",
        type="Person",
        username="localuser",
        domain=None,
        display_name="Local User",
        inbox_url="http://localhost/users/localuser/inbox",
        outbox_url="http://localhost/users/localuser/outbox",
        public_key_pem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
    )
    db.add(local)
    await db.commit()

    result = await proxy_subscribe(db, local)
    assert result is None


# -- proxy_unsubscribe --


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_proxy_unsubscribe(mock_delivery, db):
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    await proxy_subscribe(db, remote)
    mock_delivery.reset_mock()

    result = await proxy_unsubscribe(db, remote)
    assert result is True

    # Undo(Follow) が配送される
    mock_delivery.assert_called_once()

    # 購読解除後はis_proxy_subscribedがFalse
    assert not await is_proxy_subscribed(db, remote.id)


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_proxy_unsubscribe_nonexistent(mock_delivery, db):
    """フォローしていないアクターの解除はFalseを返す"""
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    result = await proxy_unsubscribe(db, remote)
    assert result is False
    mock_delivery.assert_not_called()


# -- is_proxy_subscribed --


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_is_proxy_subscribed(mock_delivery, db):
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    assert not await is_proxy_subscribed(db, remote.id)
    await proxy_subscribe(db, remote)
    assert await is_proxy_subscribed(db, remote.id)


# -- has_real_local_follower --


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_has_real_local_follower_false_when_only_proxy(mock_delivery, db):
    """proxyのみがフォローしている場合はFalse"""
    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    await proxy_subscribe(db, remote)
    # proxyのフォローをaccepted状態にする
    from sqlalchemy import update

    proxy_user = await get_proxy_actor(db)
    await db.execute(
        update(Follow)
        .where(
            Follow.follower_id == proxy_user.actor.id,
            Follow.following_id == remote.id,
        )
        .values(accepted=True)
    )
    await db.commit()

    assert not await has_real_local_follower(db, remote.id)


async def test_has_real_local_follower_true_when_real_user(db):
    """実ユーザーがフォローしている場合はTrue"""
    from app.services.user_service import create_user

    user = await create_user(db, "alice", "alice@test.com", "password1234")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    follow = Follow(
        id=uuid.uuid4(),
        follower_id=user.actor.id,
        following_id=remote.id,
        accepted=True,
    )
    db.add(follow)
    await db.commit()

    assert await has_real_local_follower(db, remote.id)


# -- get_system_actor_ids --


async def test_get_system_actor_ids(db):
    # Valkeyキャッシュをリセットしてテスト間の汚染を防止
    from app.services.proxy_service import _SYSTEM_IDS_VALKEY_KEY
    from app.valkey_client import valkey

    await valkey.delete(_SYSTEM_IDS_VALKEY_KEY)

    await ensure_system_accounts(db)
    ids = await get_system_actor_ids(db)
    assert len(ids) >= 2  # instance.actor + system.proxy

    proxy_user = await get_proxy_actor(db)
    assert proxy_user.actor.id in ids


# -- create.py フィルタリング統合テスト --


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_followers_only_note_discarded_when_proxy_only(mock_delivery, db):
    """proxyのみがフォローしている場合、フォロワー限定ノートは保存されない"""
    from app.activitypub.handlers.create import handle_create_note

    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    # proxyで購読してacceptedにする
    await proxy_subscribe(db, remote)
    from sqlalchemy import update

    proxy_user = await get_proxy_actor(db)
    await db.execute(
        update(Follow)
        .where(
            Follow.follower_id == proxy_user.actor.id,
            Follow.following_id == remote.id,
        )
        .values(accepted=True)
    )
    await db.commit()

    # フォロワー限定ノートを受信
    note_data = {
        "id": f"https://remote.example.com/notes/{uuid.uuid4()}",
        "type": "Note",
        "attributedTo": remote.ap_id,
        "content": "<p>Followers-only post</p>",
        "to": [f"{remote.ap_id}/followers"],
        "cc": [],
        "published": "2026-03-24T00:00:00Z",
    }
    activity = {"type": "Create", "actor": remote.ap_id, "object": note_data}

    await handle_create_note(db, activity, note_data)

    # ノートが保存されていないことを確認
    from sqlalchemy import select

    from app.models.note import Note

    result = await db.execute(select(Note).where(Note.ap_id == note_data["id"]))
    assert result.scalar_one_or_none() is None


async def test_followers_only_note_saved_when_real_follower(db):
    """実ユーザーがフォローしている場合、フォロワー限定ノートは保存される"""
    from app.activitypub.handlers.create import handle_create_note
    from app.services.user_service import create_user

    user = await create_user(db, "bob", "bob@test.com", "password1234")
    remote = _make_remote_actor()
    db.add(remote)
    await db.commit()

    # 実ユーザーでフォロー
    follow = Follow(
        id=uuid.uuid4(),
        follower_id=user.actor.id,
        following_id=remote.id,
        accepted=True,
    )
    db.add(follow)
    await db.commit()

    note_data = {
        "id": f"https://remote.example.com/notes/{uuid.uuid4()}",
        "type": "Note",
        "attributedTo": remote.ap_id,
        "content": "<p>Followers-only post</p>",
        "to": [f"{remote.ap_id}/followers"],
        "cc": [],
        "published": "2026-03-24T00:00:00Z",
    }
    activity = {"type": "Create", "actor": remote.ap_id, "object": note_data}

    with patch("app.valkey_client.valkey", new_callable=AsyncMock):
        await handle_create_note(db, activity, note_data)

    from sqlalchemy import select

    from app.models.note import Note

    result = await db.execute(select(Note).where(Note.ap_id == note_data["id"]))
    note = result.scalar_one_or_none()
    assert note is not None
    assert note.visibility == "followers"


async def test_public_note_saved_when_proxy_only(db):
    """proxyのみがフォローしていても公開ノートは保存される"""
    from app.activitypub.handlers.create import handle_create_note

    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    remote = _make_remote_actor(username="publicuser")
    db.add(remote)
    await db.commit()

    note_data = {
        "id": f"https://remote.example.com/notes/{uuid.uuid4()}",
        "type": "Note",
        "attributedTo": remote.ap_id,
        "content": "<p>Public post</p>",
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [f"{remote.ap_id}/followers"],
        "published": "2026-03-24T00:00:00Z",
    }
    activity = {"type": "Create", "actor": remote.ap_id, "object": note_data}

    with patch("app.valkey_client.valkey", new_callable=AsyncMock):
        await handle_create_note(db, activity, note_data)

    from sqlalchemy import select

    from app.models.note import Note

    result = await db.execute(select(Note).where(Note.ap_id == note_data["id"]))
    note = result.scalar_one_or_none()
    assert note is not None
    assert note.visibility == "public"


async def test_direct_note_saved_even_without_follower(db):
    """DM投稿はフォロー関係に関係なく保存される(宛先指定で配送されるため)"""
    from app.activitypub.handlers.create import handle_create_note

    remote = _make_remote_actor(username="dmuser")
    db.add(remote)
    await db.commit()

    note_data = {
        "id": f"https://remote.example.com/notes/{uuid.uuid4()}",
        "type": "Note",
        "attributedTo": remote.ap_id,
        "content": "<p>Direct message</p>",
        "to": [],
        "cc": [],
        "published": "2026-03-24T00:00:00Z",
    }
    activity = {"type": "Create", "actor": remote.ap_id, "object": note_data}

    with patch("app.valkey_client.valkey", new_callable=AsyncMock):
        await handle_create_note(db, activity, note_data)

    from sqlalchemy import select

    from app.models.note import Note

    result = await db.execute(select(Note).where(Note.ap_id == note_data["id"]))
    note = result.scalar_one_or_none()
    assert note is not None
    assert note.visibility == "direct"


async def test_followers_note_saved_when_no_proxy_no_follower(db):
    """proxyも実ユーザーもフォローしていない場合、followers-onlyでも保存される
    (inbox配送された正当な理由があるため)"""
    from app.activitypub.handlers.create import handle_create_note

    remote = _make_remote_actor(username="nofollowuser")
    db.add(remote)
    await db.commit()

    note_data = {
        "id": f"https://remote.example.com/notes/{uuid.uuid4()}",
        "type": "Note",
        "attributedTo": remote.ap_id,
        "content": "<p>Followers post no proxy</p>",
        "to": [f"{remote.ap_id}/followers"],
        "cc": [],
        "published": "2026-03-24T00:00:00Z",
    }
    activity = {"type": "Create", "actor": remote.ap_id, "object": note_data}

    with patch("app.valkey_client.valkey", new_callable=AsyncMock):
        await handle_create_note(db, activity, note_data)

    from sqlalchemy import select

    from app.models.note import Note

    result = await db.execute(select(Note).where(Note.ap_id == note_data["id"]))
    note = result.scalar_one_or_none()
    assert note is not None
    assert note.visibility == "followers"
