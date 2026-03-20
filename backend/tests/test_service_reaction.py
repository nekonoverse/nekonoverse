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
    # Emoji reactions are sent to unknown servers (Like + content)
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
    # Emoji reactions are sent to unknown servers
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
    # Emoji reactions are sent to unknown servers
    await add_reaction(db, test_user, note, "\U0001f600")

    # Check that delivery jobs were created for both targets
    result = await db.execute(select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id))
    jobs = result.scalars().all()
    target_urls = {j.target_inbox_url for j in jobs}

    # Should include author's shared inbox and follower's shared inbox
    assert remote_author.shared_inbox_url in target_urls or remote_author.inbox_url in target_urls
    assert remote_follower.shared_inbox_url in target_urls or remote_follower.inbox_url in target_urls


async def test_add_reaction_sends_like_or_emoji_react(db, test_user, mock_valkey):
    """Reaction to a remote note delivers Like or EmojiReact (software-dependent)."""
    from unittest.mock import AsyncMock, patch

    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="fedib_author", domain="fedibird.example"
    )
    note = await make_note(db, remote_author, local=False)

    async def mock_software(domain):
        return "fedibird" if "fedibird" in domain else None

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await add_reaction(db, test_user, note, "\U0001f600")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) >= 1
    # Fedibird supports EmojiReact
    types = {j.payload["type"] for j in jobs}
    assert "EmojiReact" in types

    for j in jobs:
        assert j.payload["content"] == "\U0001f600"


async def test_remove_reaction_sends_undo_like_and_undo_emoji_react(
    db, test_user, mock_valkey
):
    """Undo sends Undo(EmojiReact) or Undo(Like) depending on software."""
    from unittest.mock import AsyncMock, patch

    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction, remove_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="fedib_author2", domain="fedibird2.example"
    )
    note = await make_note(db, remote_author, local=False)

    async def mock_software(domain):
        return "fedibird" if "fedibird" in domain else None

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await add_reaction(db, test_user, note, "\u2764")

    # Clear add jobs
    prev = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    for j in prev.scalars().all():
        await db.delete(j)
    await db.flush()

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await remove_reaction(db, test_user, note, "\u2764")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) >= 1

    # Fedibird → Undo(EmojiReact)
    inner_types = {j.payload["object"]["type"] for j in jobs}
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
    # Use ⭐ (favourite) — sent to all servers regardless of software
    await add_reaction(db, test_user, note, "\u2b50")

    # Clear previous delivery jobs
    prev_result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    for job in prev_result.scalars().all():
        await db.delete(job)
    await db.flush()

    await remove_reaction(db, test_user, note, "\u2b50")

    # Undo should have been delivered to follower
    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) >= 1
    target_urls = {j.target_inbox_url for j in jobs}
    assert remote_follower.shared_inbox_url in target_urls or remote_follower.inbox_url in target_urls


async def test_favourite_sends_like_without_content(db, test_user, mock_valkey):
    """☆ favourite sends Like without content/_misskey_reaction to all servers."""
    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(db, username="fav_author", domain="fav.example")
    note = await make_note(db, remote_author, local=False)
    await add_reaction(db, test_user, note, "\u2b50")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    assert len(jobs) >= 1
    for j in jobs:
        assert j.payload["type"] == "Like"
        assert "content" not in j.payload
        assert "_misskey_reaction" not in j.payload


async def test_emoji_reaction_not_sent_to_mastodon(db, test_user, mock_valkey):
    """Emoji reactions are NOT delivered to Mastodon servers."""
    from unittest.mock import AsyncMock, patch

    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="masto_author", domain="mastodon.example"
    )
    note = await make_note(db, remote_author, local=False)

    # Mock: mastodon.example returns "mastodon" software
    async def mock_software(domain):
        return "mastodon" if "mastodon" in domain else None

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await add_reaction(db, test_user, note, "👍")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    # No delivery to mastodon.example for non-favourite emoji
    mastodon_jobs = [j for j in jobs if "mastodon" in j.target_inbox_url]
    assert len(mastodon_jobs) == 0


async def test_emoji_reaction_sent_to_unknown_server(db, test_user, mock_valkey):
    """Emoji reactions ARE delivered to unknown servers as EmojiReact."""
    from unittest.mock import AsyncMock, patch

    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="unknown_author", domain="unknown.example"
    )
    note = await make_note(db, remote_author, local=False)

    # Mock: unknown.example returns None (unknown software)
    async def mock_software(domain):
        return None

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await add_reaction(db, test_user, note, "👍")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    unknown_jobs = [j for j in jobs if "unknown" in j.target_inbox_url]
    assert len(unknown_jobs) >= 1
    assert unknown_jobs[0].payload["type"] == "EmojiReact"
    assert unknown_jobs[0].payload["content"] == "👍"


async def test_emoji_reaction_sends_emoji_react_to_neko(db, test_user, mock_valkey):
    """Emoji reactions are sent as EmojiReact to nekonoverse instances."""
    from unittest.mock import AsyncMock, patch

    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="neko_author", domain="neko.example"
    )
    note = await make_note(db, remote_author, local=False)

    async def mock_software(domain):
        return "nekonoverse" if "neko" in domain else None

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await add_reaction(db, test_user, note, "👍")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    neko_jobs = [j for j in jobs if "neko" in j.target_inbox_url]
    assert len(neko_jobs) >= 1
    assert neko_jobs[0].payload["type"] == "EmojiReact"
    assert neko_jobs[0].payload["content"] == "👍"


async def test_emoji_reaction_sends_emoji_react_to_misskey(db, test_user, mock_valkey):
    """Emoji reactions are sent as EmojiReact to Misskey instances (Misskey supports it)."""
    from unittest.mock import AsyncMock, patch

    from app.models.delivery import DeliveryJob
    from app.services.reaction_service import add_reaction
    from sqlalchemy import select

    remote_author = await make_remote_actor(
        db, username="mk_author", domain="misskey.example"
    )
    note = await make_note(db, remote_author, local=False)

    async def mock_software(domain):
        return "misskey" if "misskey" in domain else None

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await add_reaction(db, test_user, note, "👍")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()
    mk_jobs = [j for j in jobs if "misskey" in j.target_inbox_url]
    assert len(mk_jobs) >= 1
    assert mk_jobs[0].payload["type"] == "EmojiReact"
    assert mk_jobs[0].payload["content"] == "👍"


async def test_add_reaction_custom_emoji_strips_domain(db, test_user, mock_valkey):
    """Remote custom emoji reaction uses bare :shortcode: in activity content.

    Misskey's isCustomEmojiRegexp only accepts :name: or :name@.: — the
    domain-qualified :name@host: is silently converted to a heart.  We strip
    the domain in the outgoing activity and let the tag carry the image URL.
    """
    from unittest.mock import AsyncMock, patch

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

    # Mock: emoji.example is not Mastodon → will receive EmojiReact
    async def mock_software(domain):
        return "misskey" if "emoji" in domain else None

    with patch("app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, side_effect=mock_software):
        await add_reaction(db, test_user, note, ":blobheart@remote.example:")

    result = await db.execute(
        select(DeliveryJob).where(DeliveryJob.actor_id == test_user.actor.id)
    )
    jobs = result.scalars().all()

    assert len(jobs) >= 1
    activity = jobs[0].payload
    assert activity["type"] == "EmojiReact"

    # content must use bare shortcode (no @domain)
    assert activity["content"] == ":blobheart:"

    # tag must carry the emoji metadata
    assert activity.get("tag")
    assert activity["tag"][0]["name"] == ":blobheart:"
    assert activity["tag"][0]["icon"]["url"] == "https://remote.example/emoji/blobheart.png"
