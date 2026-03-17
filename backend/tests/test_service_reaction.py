import pytest

from tests.conftest import make_note, make_remote_actor


async def test_add_reaction(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    reaction = await add_reaction(db, test_user, note, "\U0001f600")
    assert reaction.emoji == "\U0001f600"
    assert note.reactions_count == 1


async def test_add_reaction_invalid_emoji(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    with pytest.raises(ValueError, match="Invalid emoji"):
        await add_reaction(db, test_user, note, "not-an-emoji")


async def test_add_reaction_duplicate(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    with pytest.raises(ValueError, match="Already reacted"):
        await add_reaction(db, test_user, note, "\U0001f600")


async def test_add_reaction_different_emoji_ok(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    r2 = await add_reaction(db, test_user, note, "\u2764")
    assert r2.emoji == "\u2764"
    assert note.reactions_count == 2


async def test_remove_reaction(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction, remove_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    await remove_reaction(db, test_user, note, "\U0001f600")
    assert note.reactions_count == 0


async def test_remove_reaction_not_found(db, test_user, mock_valkey):
    from app.services.reaction_service import remove_reaction
    note = await make_note(db, test_user.actor)
    with pytest.raises(ValueError):
        await remove_reaction(db, test_user, note, "\U0001f600")


async def test_add_reaction_remote_note_enqueues(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction
    remote_actor = await make_remote_actor(db)
    note = await make_note(db, remote_actor, local=False)
    await add_reaction(db, test_user, note, "\U0001f600")
    mock_valkey.lpush.assert_called()


async def test_remove_reaction_count_floor(db, test_user, mock_valkey):
    from app.services.reaction_service import add_reaction, remove_reaction
    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")
    note.reactions_count = 0  # Force to 0
    await remove_reaction(db, test_user, note, "\U0001f600")
    assert note.reactions_count >= 0


async def test_add_reaction_fanout_to_followers(db, test_user, mock_valkey):
    """Reaction delivery fans out to the reactor's followers' inboxes."""
    from app.models.follow import Follow
    from app.services.reaction_service import add_reaction

    remote_follower = await make_remote_actor(db, username="follower1", domain="f1.example")
    # Create accepted follow: remote_follower follows test_user
    follow = Follow(
        follower_id=remote_follower.id,
        following_id=test_user.actor.id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")

    # Should have delivered to the follower's shared inbox
    calls = [str(c) for c in mock_valkey.lpush.call_args_list]
    assert any("delivery:queue" in c for c in calls)


async def test_add_reaction_remote_note_includes_author_and_followers(
    db, test_user, mock_valkey
):
    """Reaction to a remote note delivers to both author and reactor's followers."""
    from app.models.delivery import DeliveryJob
    from app.models.follow import Follow
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(db, username="author", domain="a.example")
    remote_follower = await make_remote_actor(db, username="follower2", domain="f2.example")

    follow = Follow(
        follower_id=remote_follower.id,
        following_id=test_user.actor.id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    note = await make_note(db, remote_author, local=False)
    await add_reaction(db, test_user, note, "\U0001f600")

    # Check that delivery jobs were created for both targets
    result = await db.execute(select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id))
    jobs = result.scalars().all()
    target_urls = {j.target_inbox_url for j in jobs}

    # Should include author's shared inbox and follower's shared inbox
    assert remote_author.shared_inbox_url in target_urls or remote_author.inbox_url in target_urls
    assert remote_follower.shared_inbox_url in target_urls or remote_follower.inbox_url in target_urls


async def test_add_reaction_sends_like_and_emoji_react(db, test_user, mock_valkey):
    """Reaction to a remote note delivers both Like and EmojiReact activities."""
    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="fedib_author", domain="fedibird.example"
    )
    note = await make_note(db, remote_author, local=False)
    await add_reaction(db, test_user, note, "\U0001f600")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    # payload is JSONB (already a dict)
    types = {j.payload["type"] for j in jobs}
    assert "Like" in types
    assert "EmojiReact" in types

    # Both should have the emoji in content
    for j in jobs:
        assert j.payload["content"] == "\U0001f600"


async def test_remove_reaction_sends_undo_like_and_undo_emoji_react(
    db, test_user, mock_valkey
):
    """Undo sends both Undo(Like) and Undo(EmojiReact)."""
    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction, remove_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="fedib_author2", domain="fedibird2.example"
    )
    note = await make_note(db, remote_author, local=False)
    await add_reaction(db, test_user, note, "\u2764")

    # Clear add jobs
    prev = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    for j in prev.scalars().all():
        await db.delete(j)
    await db.flush()

    await remove_reaction(db, test_user, note, "\u2764")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()

    # payload is JSONB (already a dict) — all should be Undo wrapping Like or EmojiReact
    inner_types = {j.payload["object"]["type"] for j in jobs}
    assert "Like" in inner_types
    assert "EmojiReact" in inner_types


async def test_remove_reaction_fanout_undo(db, test_user, mock_valkey):
    """Undo(Like) is also delivered to followers, not just note author."""
    from app.models.delivery import DeliveryJob
    from app.models.follow import Follow
    from app.services.reaction_service import add_reaction, remove_reaction
    from sqlalchemy import select

    remote_follower = await make_remote_actor(db, username="follower3", domain="f3.example")
    follow = Follow(
        follower_id=remote_follower.id,
        following_id=test_user.actor.id,
        accepted=True,
    )
    db.add(follow)
    await db.flush()

    note = await make_note(db, test_user.actor)
    await add_reaction(db, test_user, note, "\U0001f600")

    # Clear previous delivery jobs
    prev_result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    for job in prev_result.scalars().all():
        await db.delete(job)
    await db.flush()

    await remove_reaction(db, test_user, note, "\U0001f600")

    # Undo should have been delivered to follower
    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) >= 1
    target_urls = {j.target_inbox_url for j in jobs}
    assert remote_follower.shared_inbox_url in target_urls or remote_follower.inbox_url in target_urls


async def test_add_reaction_custom_emoji_strips_domain(db, test_user, mock_valkey):
    """Remote custom emoji reaction uses bare :shortcode: in activity content.

    Misskey's isCustomEmojiRegexp only accepts :name: or :name@.: — the
    domain-qualified :name@host: is silently converted to a heart.  We strip
    the domain in the outgoing activity and let the tag carry the image URL.
    """
    from app.models.custom_emoji import CustomEmoji
    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    # Create a cached remote emoji (as if seen on a remote note)
    remote_emoji = CustomEmoji(
        shortcode="blobheart",
        domain="remote.example",
        url="https://remote.example/emoji/blobheart.png",
    )
    db.add(remote_emoji)
    await db.flush()

    remote_author = await make_remote_actor(
        db, username="emoji_author", domain="emoji.example"
    )
    note = await make_note(db, remote_author, local=False)
    await add_reaction(db, test_user, note, ":blobheart@remote.example:")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()

    like_jobs = [j for j in jobs if j.payload["type"] == "Like"]
    react_jobs = [j for j in jobs if j.payload["type"] == "EmojiReact"]

    assert len(like_jobs) >= 1
    assert len(react_jobs) >= 1

    like = like_jobs[0].payload
    react = react_jobs[0].payload

    # content/_misskey_reaction must use bare shortcode (no @domain)
    assert like["content"] == ":blobheart:"
    assert like["_misskey_reaction"] == ":blobheart:"
    assert react["content"] == ":blobheart:"

    # tag must carry the emoji metadata
    assert like.get("tag")
    assert like["tag"][0]["name"] == ":blobheart:"
    assert like["tag"][0]["icon"]["url"] == "https://remote.example/emoji/blobheart.png"
