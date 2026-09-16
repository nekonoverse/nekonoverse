"""受信アクティビティの操作主体が署名者 (activity.actor) に限定されることの回帰テスト。"""

from sqlalchemy import func, select

from app.activitypub.handlers.create import handle_create
from app.activitypub.handlers.undo import handle_undo
from app.models.follow import Follow
from app.models.note import Note
from app.models.poll_vote import PollVote
from app.models.reaction import Reaction
from app.models.user_block import UserBlock
from app.services.note_service import get_note_by_ap_id
from tests.conftest import make_note, make_remote_actor

# ── Undo ─────────────────────────────────────────────────────────────────


async def test_undo_follow_of_other_actor_rejected(db, mock_valkey, test_user):
    victim = await make_remote_actor(db, username="victim", domain="shared.example")
    signer = await make_remote_actor(db, username="signer", domain="other.example")
    follow = Follow(follower_id=victim.id, following_id=test_user.actor_id, accepted=True)
    db.add(follow)
    await db.flush()

    await handle_undo(db, {
        "type": "Undo",
        "actor": signer.ap_id,
        "object": {"type": "Follow", "actor": victim.ap_id, "object": test_user.actor.ap_id},
    })

    result = await db.execute(select(Follow).where(Follow.id == follow.id))
    assert result.scalar_one_or_none() is not None


async def test_undo_follow_with_actor_object(db, mock_valkey, test_user):
    """inner.actor がオブジェクト形式でも署名者と一致すれば取り消せる。"""
    remote = await make_remote_actor(db, username="objactor", domain="objactor.example")
    follow = Follow(follower_id=remote.id, following_id=test_user.actor_id, accepted=True)
    db.add(follow)
    await db.flush()

    await handle_undo(db, {
        "type": "Undo",
        "actor": remote.ap_id,
        "object": {
            "type": "Follow",
            "actor": {"id": remote.ap_id, "type": "Person"},
            "object": test_user.actor.ap_id,
        },
    })

    result = await db.execute(select(Follow).where(Follow.id == follow.id))
    assert result.scalar_one_or_none() is None


async def test_undo_block_of_other_actor_rejected(db, mock_valkey, test_user):
    victim = await make_remote_actor(db, username="blocker", domain="blk.example")
    signer = await make_remote_actor(db, username="spoofer", domain="spoof.example")
    block = UserBlock(actor_id=victim.id, target_id=test_user.actor_id)
    db.add(block)
    await db.flush()

    await handle_undo(db, {
        "type": "Undo",
        "actor": signer.ap_id,
        "object": {"type": "Block", "actor": victim.ap_id, "object": test_user.actor.ap_id},
    })

    result = await db.execute(select(UserBlock).where(UserBlock.id == block.id))
    assert result.scalar_one_or_none() is not None


async def test_undo_reaction_by_id_of_other_actor_rejected(db, mock_valkey, test_user):
    """inner.actor を省略し、他人のリアクション ID を指定しても削除されない。"""
    owner = await make_remote_actor(db, username="reactor", domain="react.example")
    signer = await make_remote_actor(db, username="intruder", domain="intrude.example")
    note = await make_note(db, test_user.actor)
    reaction = Reaction(
        actor_id=owner.id,
        note_id=note.id,
        emoji="❤",
        ap_id="http://react.example/likes/1",
    )
    db.add(reaction)
    note.reactions_count = 1
    await db.flush()

    await handle_undo(db, {
        "type": "Undo",
        "actor": signer.ap_id,
        "object": {"type": "Like", "id": reaction.ap_id, "object": note.ap_id},
    })

    result = await db.execute(select(Reaction).where(Reaction.id == reaction.id))
    assert result.scalar_one_or_none() is not None
    await db.refresh(note)
    assert note.reactions_count == 1


async def test_undo_reaction_without_inner_actor_by_owner(db, mock_valkey, test_user):
    """inner.actor が無い場合は署名者自身のリアクションとして取り消せる (互換性)。"""
    owner = await make_remote_actor(db, username="noinner", domain="noinner.example")
    note = await make_note(db, test_user.actor)
    reaction = Reaction(
        actor_id=owner.id,
        note_id=note.id,
        emoji="❤",
        ap_id="http://noinner.example/likes/1",
    )
    db.add(reaction)
    note.reactions_count = 1
    await db.flush()

    await handle_undo(db, {
        "type": "Undo",
        "actor": owner.ap_id,
        "object": {"type": "Like", "id": reaction.ap_id, "object": note.ap_id},
    })

    result = await db.execute(select(Reaction).where(Reaction.id == reaction.id))
    assert result.scalar_one_or_none() is None


# ── Create(Note) ─────────────────────────────────────────────────────────


def _create_activity(actor_ap_id: str, note_id: str, attributed_to: object) -> dict:
    return {
        "type": "Create",
        "actor": actor_ap_id,
        "object": {
            "type": "Note",
            "id": note_id,
            "attributedTo": attributed_to,
            "content": "<p>hello</p>",
            "published": "2025-06-01T00:00:00Z",
            "to": ["https://www.w3.org/ns/activitystreams#Public"],
            "cc": [],
        },
    }


async def test_create_note_attributed_to_same_domain_other_actor_rejected(db, mock_valkey):
    famous = await make_remote_actor(db, username="famous", domain="big.example")
    signer = await make_remote_actor(db, username="nobody", domain="big.example")
    note_id = "http://big.example/notes/spoofed"

    await handle_create(db, _create_activity(signer.ap_id, note_id, famous.ap_id))

    count = await db.scalar(select(func.count()).where(Note.ap_id == note_id))
    assert count == 0


async def test_create_note_attributed_to_list_including_signer(db, mock_valkey):
    """PeerTube 形式 (Person と Group の配列) は署名者が含まれていれば受理する。"""
    signer = await make_remote_actor(db, username="tuber", domain="tube.example")
    note_id = "http://tube.example/videos/1"
    attributed = [
        {"type": "Person", "id": signer.ap_id},
        {"type": "Group", "id": "http://tube.example/video-channels/ch"},
    ]

    await handle_create(db, _create_activity(signer.ap_id, note_id, attributed))

    note = await get_note_by_ap_id(db, note_id)
    assert note is not None
    assert note.actor_id == signer.id


async def test_create_note_without_attributed_to_uses_signer(db, mock_valkey):
    signer = await make_remote_actor(db, username="noattr", domain="noattr.example")
    note_id = "http://noattr.example/notes/1"

    await handle_create(db, _create_activity(signer.ap_id, note_id, None))

    note = await get_note_by_ap_id(db, note_id)
    assert note is not None
    assert note.actor_id == signer.id


# ── 投票 ─────────────────────────────────────────────────────────────────


async def _local_poll(db, actor) -> Note:
    note = await make_note(db, actor, content="poll")
    note.is_poll = True
    note.poll_options = [{"title": "Yes", "votes_count": 0}, {"title": "No", "votes_count": 0}]
    await db.flush()
    return note


def _vote_activity(signer_ap_id: str, attributed_to: str, poll: Note, n: int) -> dict:
    return {
        "type": "Create",
        "actor": signer_ap_id,
        "object": {
            "type": "Note",
            "id": f"{signer_ap_id}/votes/{n}",
            "attributedTo": attributed_to,
            "name": "Yes",
            "inReplyTo": poll.ap_id,
            "to": [poll.actor.ap_id],
        },
    }


async def test_poll_vote_as_other_actor_rejected(db, mock_valkey, test_user, test_user_b):
    poll = await _local_poll(db, test_user.actor)
    signer = await make_remote_actor(db, username="voter", domain="vote.example")

    await handle_create(db, _vote_activity(signer.ap_id, test_user_b.actor.ap_id, poll, 1))

    votes = (await db.execute(select(PollVote).where(PollVote.note_id == poll.id))).scalars()
    assert list(votes) == []


async def test_poll_vote_by_signer_recorded(db, mock_valkey, test_user):
    poll = await _local_poll(db, test_user.actor)
    signer = await make_remote_actor(db, username="voter2", domain="vote2.example")

    await handle_create(db, _vote_activity(signer.ap_id, signer.ap_id, poll, 1))

    votes = list(
        (await db.execute(select(PollVote).where(PollVote.note_id == poll.id))).scalars()
    )
    assert [(v.actor_id, v.choice_index) for v in votes] == [(signer.id, 0)]
