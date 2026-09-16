"""ブロックが宛先ローカルユーザー単位で判定され、インスタンス全体に波及しないことの回帰テスト。

以前は process_inbox_activity で「誰か1人でもこのリモートアクターをブロックしていれば」
activity 全体を握りつぶしていたため、無関係な他ユーザー宛の Follow/Like/Announce まで
インスタンス全体で届かなくなっていた。
"""

from sqlalchemy import select

from app.activitypub.handlers.announce import handle_announce
from app.activitypub.handlers.follow import handle_follow
from app.activitypub.handlers.like import handle_like
from app.activitypub.routes import process_inbox_activity
from app.models.follow import Follow
from app.models.note import Note
from app.models.reaction import Reaction
from app.services.block_service import block_actor
from tests.conftest import make_note, make_remote_actor


async def _block(db, blocker, target):
    await block_actor(db, blocker, target)
    await db.commit()


# ── Follow: ブロックした本人には Reject、無関係な相手へは通常通り ──────────


async def test_follow_from_blocked_actor_rejected_not_saved(db, test_user, mock_valkey):
    remote = await make_remote_actor(db, username="blockedfollower", domain="bf.example")
    await _block(db, test_user, remote)

    await handle_follow(db, {
        "type": "Follow",
        "id": "http://bf.example/activities/follow1",
        "actor": remote.ap_id,
        "object": test_user.actor.ap_id,
    })

    follow = (await db.execute(select(Follow).where(
        Follow.follower_id == remote.id, Follow.following_id == test_user.actor_id
    ))).scalar_one_or_none()
    assert follow is None
    # ブロックしたユーザーへの Reject 配送がキューされている
    mock_valkey.lpush.assert_called()


async def test_follow_to_unrelated_user_unaffected_by_others_block(
    db, test_user, test_user_b, mock_valkey
):
    """test_user がブロックしていても、無関係な test_user_b への Follow は通常通り成立する。"""
    remote = await make_remote_actor(db, username="popular", domain="popular.example")
    await _block(db, test_user, remote)

    await handle_follow(db, {
        "type": "Follow",
        "id": "http://popular.example/activities/follow2",
        "actor": remote.ap_id,
        "object": test_user_b.actor.ap_id,
    })

    follow = (await db.execute(select(Follow).where(
        Follow.follower_id == remote.id, Follow.following_id == test_user_b.actor_id
    ))).scalar_one_or_none()
    assert follow is not None
    assert follow.accepted is True


# ── Like/EmojiReact: ノート作者本人には記録しない、無関係な相手には記録する ──


async def test_reaction_from_blocked_actor_on_own_note_dropped(db, test_user, mock_valkey):
    remote = await make_remote_actor(db, username="blockedreactor", domain="br.example")
    await _block(db, test_user, remote)
    note = await make_note(db, test_user.actor)
    await db.commit()

    await handle_like(db, {
        "type": "Like",
        "id": "http://br.example/activities/like1",
        "actor": remote.ap_id,
        "object": note.ap_id,
    })

    reaction = (await db.execute(
        select(Reaction).where(Reaction.note_id == note.id)
    )).scalar_one_or_none()
    assert reaction is None


async def test_reaction_from_blocked_actor_on_unrelated_note_unaffected(
    db, test_user, test_user_b, mock_valkey
):
    """test_user がブロックしていても、無関係な test_user_b のノートへの Like は記録される。"""
    remote = await make_remote_actor(db, username="popularreactor", domain="pr.example")
    await _block(db, test_user, remote)
    note = await make_note(db, test_user_b.actor)
    await db.commit()

    await handle_like(db, {
        "type": "Like",
        "id": "http://pr.example/activities/like2",
        "actor": remote.ap_id,
        "object": note.ap_id,
    })

    reaction = (await db.execute(
        select(Reaction).where(Reaction.note_id == note.id)
    )).scalar_one_or_none()
    assert reaction is not None
    assert reaction.emoji == "⭐"


# ── Announce: ノート作者本人には記録しない、無関係な相手には記録する ────────


async def test_announce_from_blocked_actor_on_own_note_dropped(db, test_user, mock_valkey):
    remote = await make_remote_actor(db, username="blockedbooster", domain="bb.example")
    await _block(db, test_user, remote)
    note = await make_note(db, test_user.actor, content="original")
    await db.commit()

    await handle_announce(db, {
        "id": "http://bb.example/activities/announce1",
        "type": "Announce",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [],
        "published": "2026-03-06T12:00:00Z",
    })

    announce = (await db.execute(
        select(Note).where(Note.renote_of_id == note.id)
    )).scalar_one_or_none()
    assert announce is None
    await db.refresh(note)
    assert note.renotes_count == 0


async def test_announce_from_blocked_actor_on_unrelated_note_unaffected(
    db, test_user, test_user_b, mock_valkey
):
    """test_user がブロックしていても、無関係な test_user_b のノートへの Announce は記録される。"""
    remote = await make_remote_actor(db, username="popularbooster", domain="pb.example")
    await _block(db, test_user, remote)
    note = await make_note(db, test_user_b.actor, content="original2")
    await db.commit()

    await handle_announce(db, {
        "id": "http://pb.example/activities/announce2",
        "type": "Announce",
        "actor": remote.ap_id,
        "object": note.ap_id,
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [],
        "published": "2026-03-06T12:00:00Z",
    })

    announce = (await db.execute(
        select(Note).where(Note.renote_of_id == note.id)
    )).scalar_one_or_none()
    assert announce is not None
    await db.refresh(note)
    assert note.renotes_count == 1


# ── process_inbox_activity 全体でのインスタンス幅回帰確認 ──────────────────


async def test_process_inbox_activity_no_longer_drops_globally(
    db, test_user, test_user_b, mock_valkey
):
    """process_inbox_activity レベルでも、1人の block が他ユーザー宛の活動を止めない。"""
    remote = await make_remote_actor(db, username="globalcheck", domain="gc.example")
    await _block(db, test_user, remote)

    await process_inbox_activity(db, {
        "type": "Follow",
        "id": "http://gc.example/activities/follow3",
        "actor": remote.ap_id,
        "object": test_user_b.actor.ap_id,
    })

    follow = (await db.execute(select(Follow).where(
        Follow.follower_id == remote.id, Follow.following_id == test_user_b.actor_id
    ))).scalar_one_or_none()
    assert follow is not None
