"""Tests for the list service layer."""

import uuid
from unittest.mock import AsyncMock, patch

from app.models.actor import Actor
from app.models.follow import Follow
from app.models.note import Note
from app.services.list_service import (
    add_list_member,
    create_list,
    delete_list,
    get_exclusive_list_actor_ids,
    get_list,
    get_list_ids_for_actor,
    get_list_member_ids,
    get_list_timeline,
    get_user_lists,
    is_actor_in_any_list,
    remove_list_member,
    update_list,
)


def _make_actor(domain=None, username="testuser"):
    return Actor(
        id=uuid.uuid4(),
        ap_id=f"https://{domain or 'localhost'}/users/{username}",
        type="Person",
        username=username,
        domain=domain,
        display_name=username,
        inbox_url=f"https://{domain or 'localhost'}/users/{username}/inbox",
        outbox_url=f"https://{domain or 'localhost'}/users/{username}/outbox",
        public_key_pem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
    )


# -- CRUD --


async def test_create_list(db, test_user):
    lst = await create_list(db, test_user, "My List")
    await db.commit()
    assert lst.title == "My List"
    assert lst.replies_policy == "list"
    assert lst.exclusive is False
    assert lst.user_id == test_user.id


async def test_create_list_with_options(db, test_user):
    lst = await create_list(
        db, test_user, "Exclusive", replies_policy="none", exclusive=True
    )
    await db.commit()
    assert lst.replies_policy == "none"
    assert lst.exclusive is True


async def test_get_list(db, test_user):
    lst = await create_list(db, test_user, "Test")
    await db.commit()
    fetched = await get_list(db, lst.id)
    assert fetched is not None
    assert fetched.title == "Test"


async def test_get_list_not_found(db):
    fetched = await get_list(db, uuid.uuid4())
    assert fetched is None


async def test_get_user_lists(db, test_user):
    await create_list(db, test_user, "A")
    await create_list(db, test_user, "B")
    await db.commit()
    lists = await get_user_lists(db, test_user.id)
    assert len(lists) == 2
    assert lists[0].title == "A"
    assert lists[1].title == "B"


async def test_update_list(db, test_user):
    lst = await create_list(db, test_user, "Old")
    await db.commit()
    lst = await update_list(db, lst, title="New", replies_policy="followed", exclusive=True)
    await db.commit()
    assert lst.title == "New"
    assert lst.replies_policy == "followed"
    assert lst.exclusive is True


async def test_delete_list(db, test_user):
    lst = await create_list(db, test_user, "Delete Me")
    await db.commit()
    list_id = lst.id
    await delete_list(db, lst)
    await db.commit()
    assert await get_list(db, list_id) is None


# -- Members --


async def test_add_remove_member(db, test_user):
    lst = await create_list(db, test_user, "Members")
    actor = _make_actor(username="member1")
    db.add(actor)
    await db.commit()

    member = await add_list_member(db, lst, actor)
    await db.commit()
    assert member.actor_id == actor.id

    ids = await get_list_member_ids(db, lst.id)
    assert actor.id in ids

    await remove_list_member(db, lst, actor)
    await db.commit()
    ids = await get_list_member_ids(db, lst.id)
    assert actor.id not in ids


async def test_add_member_idempotent(db, test_user):
    lst = await create_list(db, test_user, "Idem")
    actor = _make_actor(username="idem1")
    db.add(actor)
    await db.commit()

    m1 = await add_list_member(db, lst, actor)
    m2 = await add_list_member(db, lst, actor)
    await db.commit()
    assert m1.id == m2.id


async def test_is_actor_in_any_list(db, test_user):
    lst = await create_list(db, test_user, "Any")
    actor = _make_actor(username="anytest")
    db.add(actor)
    await db.commit()

    assert not await is_actor_in_any_list(db, actor.id)
    await add_list_member(db, lst, actor)
    await db.commit()
    assert await is_actor_in_any_list(db, actor.id)


async def test_delete_list_cascades_members(db, test_user):
    lst = await create_list(db, test_user, "Cascade")
    actor = _make_actor(username="cascade1")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)
    await db.commit()

    await delete_list(db, lst)
    await db.commit()
    assert not await is_actor_in_any_list(db, actor.id)


@patch("app.services.delivery_service.enqueue_delivery", new_callable=AsyncMock)
async def test_add_remote_member_proxy_subscribe(mock_delivery, db, test_user):
    """Adding a remote actor to a list triggers proxy_subscribe."""
    from app.services.system_account_service import ensure_system_account

    await ensure_system_account(db, "system.proxy", "Proxy Subscription Actor")
    lst = await create_list(db, test_user, "Remote")
    remote = _make_actor(domain="remote.example.com", username="remoteuser")
    db.add(remote)
    await db.commit()

    await add_list_member(db, lst, remote)
    await db.commit()

    # proxy_subscribe should have been called (Follow activity sent)
    mock_delivery.assert_called_once()


# -- Timeline --


async def test_list_timeline_basic(db, test_user):
    from datetime import datetime, timezone

    lst = await create_list(db, test_user, "TL")
    actor = _make_actor(username="poster")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)

    note = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=actor.id,
        content="Hello from list",
        visibility="public",
        local=True,
        published=datetime.now(timezone.utc),
    )
    db.add(note)
    await db.commit()

    notes = await get_list_timeline(db, lst, test_user, limit=20)
    assert len(notes) == 1
    assert notes[0].content == "Hello from list"


async def test_list_timeline_replies_policy_none(db, test_user):
    from datetime import datetime, timezone

    lst = await create_list(db, test_user, "NoReplies", replies_policy="none")
    actor = _make_actor(username="noreply")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)

    parent = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=actor.id,
        content="Parent",
        visibility="public",
        local=True,
        published=datetime.now(timezone.utc),
    )
    reply = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=actor.id,
        content="Reply",
        visibility="public",
        local=True,
        in_reply_to_id=parent.id,
        published=datetime.now(timezone.utc),
    )
    db.add_all([parent, reply])
    await db.commit()

    notes = await get_list_timeline(db, lst, test_user, limit=20)
    assert len(notes) == 1
    assert notes[0].content == "Parent"


async def test_list_timeline_replies_policy_list(db, test_user):
    from datetime import datetime, timezone

    lst = await create_list(db, test_user, "ListReplies", replies_policy="list")
    actor1 = _make_actor(username="listmem1")
    actor2 = _make_actor(username="listmem2")
    outsider = _make_actor(username="outsider")
    db.add_all([actor1, actor2, outsider])
    await db.commit()
    await add_list_member(db, lst, actor1)
    await add_list_member(db, lst, actor2)

    # Note by outsider that actor1 replies to
    outsider_note = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=outsider.id,
        content="Outsider post",
        visibility="public",
        local=True,
        published=datetime.now(timezone.utc),
    )
    # Note by actor2 that actor1 replies to (both in list)
    member_note = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=actor2.id,
        content="Member post",
        visibility="public",
        local=True,
        published=datetime.now(timezone.utc),
    )
    reply_to_outsider = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=actor1.id,
        content="Reply to outsider",
        visibility="public",
        local=True,
        in_reply_to_id=outsider_note.id,
        published=datetime.now(timezone.utc),
    )
    reply_to_member = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=actor1.id,
        content="Reply to member",
        visibility="public",
        local=True,
        in_reply_to_id=member_note.id,
        published=datetime.now(timezone.utc),
    )
    db.add_all([outsider_note, member_note, reply_to_outsider, reply_to_member])
    await db.commit()

    notes = await get_list_timeline(db, lst, test_user, limit=20)
    contents = {n.content for n in notes}
    # Member post and reply-to-member should appear, reply-to-outsider should NOT
    assert "Member post" in contents
    assert "Reply to member" in contents
    assert "Reply to outsider" not in contents


# -- Exclusive --


async def test_exclusive_list_actor_ids(db, test_user):
    lst = await create_list(db, test_user, "Excl", exclusive=True)
    actor = _make_actor(username="exclmem")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)
    await db.commit()

    ids = await get_exclusive_list_actor_ids(db, test_user.id)
    assert actor.id in ids


async def test_non_exclusive_list_not_in_ids(db, test_user):
    lst = await create_list(db, test_user, "NonExcl", exclusive=False)
    actor = _make_actor(username="nonexcl")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)
    await db.commit()

    ids = await get_exclusive_list_actor_ids(db, test_user.id)
    assert actor.id not in ids


# -- Streaming helpers --


async def test_get_list_ids_for_actor(db, test_user):
    lst1 = await create_list(db, test_user, "S1")
    lst2 = await create_list(db, test_user, "S2")
    actor = _make_actor(username="streammem")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst1, actor)
    await add_list_member(db, lst2, actor)
    await db.commit()

    list_ids = await get_list_ids_for_actor(db, actor.id)
    assert set(list_ids) == {lst1.id, lst2.id}


# -- get_user_lists_for_actor --


async def test_get_user_lists_for_actor(db, test_user):
    from app.services.list_service import get_user_lists_for_actor

    lst1 = await create_list(db, test_user, "Has Actor")
    lst2 = await create_list(db, test_user, "Empty")
    actor = _make_actor(username="target1")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst1, actor)
    await db.commit()

    result = await get_user_lists_for_actor(db, test_user.id, actor.id)
    assert len(result) == 1
    assert result[0].id == lst1.id
    assert result[0].title == "Has Actor"

    # actor not in lst2
    result_ids = {r.id for r in result}
    assert lst2.id not in result_ids


async def test_get_user_lists_for_actor_empty(db, test_user):
    from app.services.list_service import get_user_lists_for_actor

    actor = _make_actor(username="nobody")
    db.add(actor)
    await db.commit()

    result = await get_user_lists_for_actor(db, test_user.id, actor.id)
    assert result == []
