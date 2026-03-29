from datetime import datetime, timezone

from sqlalchemy import select

from tests.conftest import make_note, make_remote_actor


async def test_handle_delete_note(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    remote = await make_remote_actor(db, username="del", domain="del.example")
    note = await make_note(db, remote, content="To be deleted", local=False)
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": {"type": "Tombstone", "id": note.ap_id},
    }
    await handle_delete(db, activity)
    await db.refresh(note)
    assert note.deleted_at is not None


async def test_handle_delete_string_object(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    remote = await make_remote_actor(db, username="dels", domain="dels.example")
    note = await make_note(db, remote, content="Delete me", local=False)
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": note.ap_id,
    }
    await handle_delete(db, activity)
    await db.refresh(note)
    assert note.deleted_at is not None


async def test_handle_delete_wrong_owner(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    owner = await make_remote_actor(db, username="owner", domain="own.example")
    other = await make_remote_actor(db, username="other", domain="oth.example")
    note = await make_note(db, owner, content="Not yours", local=False)
    activity = {
        "type": "Delete",
        "actor": other.ap_id,
        "object": note.ap_id,
    }
    await handle_delete(db, activity)
    await db.refresh(note)
    assert note.deleted_at is None  # Should not delete


async def test_handle_delete_nonexistent_note(db, mock_valkey):
    from app.activitypub.handlers.delete import handle_delete
    remote = await make_remote_actor(db, username="dne", domain="dne.example")
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": "http://localhost/notes/nonexistent",
    }
    await handle_delete(db, activity)  # Should not raise


# ── Delete(Person) ───────────────────────────────────────────────────────


async def test_handle_delete_person_sets_deleted_at(db, mock_valkey):
    """Delete(Person) でリモートアクターの deleted_at が設定される。"""
    from app.activitypub.handlers.delete import handle_delete

    remote = await make_remote_actor(db, username="delperson", domain="dp.example")
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": remote.ap_id,
    }
    await handle_delete(db, activity)
    await db.refresh(remote)
    assert remote.is_deleted is True
    assert remote.display_name is None
    assert remote.summary is None
    assert remote.avatar_url is None
    assert remote.header_url is None


async def test_handle_delete_person_soft_deletes_notes(db, mock_valkey):
    """Delete(Person) でリモートアクターの全ノートが論理削除される。"""
    from app.activitypub.handlers.delete import handle_delete

    remote = await make_remote_actor(db, username="dpnotes", domain="dpn.example")
    note1 = await make_note(db, remote, content="Note 1", local=False)
    note2 = await make_note(db, remote, content="Note 2", local=False)

    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": remote.ap_id,
    }
    await handle_delete(db, activity)
    await db.refresh(note1)
    await db.refresh(note2)
    assert note1.deleted_at is not None
    assert note2.deleted_at is not None


async def test_handle_delete_person_clears_follows(db, mock_valkey):
    """Delete(Person) でリモートアクターのフォロー関係がクリアされる。"""
    from app.activitypub.handlers.delete import handle_delete
    from app.models.follow import Follow

    remote = await make_remote_actor(db, username="dpfollow", domain="dpf.example")
    local = await make_remote_actor(db, username="localfollow", domain=None)
    # remote → local のフォロー
    follow = Follow(follower_id=remote.id, following_id=local.id)
    db.add(follow)
    await db.flush()

    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": remote.ap_id,
    }
    await handle_delete(db, activity)

    result = await db.execute(
        select(Follow).where(
            (Follow.follower_id == remote.id) | (Follow.following_id == remote.id)
        )
    )
    assert result.scalars().all() == []


async def test_handle_delete_person_clears_reactions(db, mock_valkey):
    """Delete(Person) でリモートアクターのリアクションが削除される。"""
    from app.activitypub.handlers.delete import handle_delete
    from app.models.reaction import Reaction

    remote = await make_remote_actor(db, username="dpreact", domain="dpr.example")
    local = await make_remote_actor(db, username="localreact", domain=None)
    note = await make_note(db, local, content="React to me", local=True)
    reaction = Reaction(actor_id=remote.id, note_id=note.id, emoji="👍")
    db.add(reaction)
    await db.flush()

    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": remote.ap_id,
    }
    await handle_delete(db, activity)

    result = await db.execute(
        select(Reaction).where(Reaction.actor_id == remote.id)
    )
    assert result.scalars().all() == []


async def test_handle_delete_person_ignores_local(db, mock_valkey):
    """Delete(Person) はローカルアクターに対しては無視する。"""
    from app.activitypub.handlers.delete import handle_delete

    local = await make_remote_actor(db, username="localignore", domain=None)
    # ローカルアクターの ap_id を設定
    local.ap_id = f"http://localhost/users/localignore"
    await db.flush()

    activity = {
        "type": "Delete",
        "actor": local.ap_id,
        "object": local.ap_id,
    }
    await handle_delete(db, activity)
    await db.refresh(local)
    assert local.is_deleted is False


async def test_handle_delete_person_with_person_type(db, mock_valkey):
    """Delete activity の object が Person タイプの dict でも処理できる。"""
    from app.activitypub.handlers.delete import handle_delete

    remote = await make_remote_actor(db, username="dptype", domain="dpt.example")
    activity = {
        "type": "Delete",
        "actor": remote.ap_id,
        "object": {"type": "Person", "id": remote.ap_id},
    }
    await handle_delete(db, activity)
    await db.refresh(remote)
    assert remote.is_deleted is True
