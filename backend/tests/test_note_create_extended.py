"""Extended tests for note creation — create_note with various options."""

from app.services.note_service import create_note


async def test_create_note_public(db, mock_valkey, test_user):
    """Create a basic public note."""
    note = await create_note(db, test_user, "Hello, world!")
    assert note is not None
    assert note.visibility == "public"
    assert note.source == "Hello, world!"
    assert note.local is True


async def test_create_note_unlisted(db, mock_valkey, test_user):
    note = await create_note(db, test_user, "Unlisted note", visibility="unlisted")
    assert note.visibility == "unlisted"
    public = "https://www.w3.org/ns/activitystreams#Public"
    assert public in note.cc


async def test_create_note_followers_only(db, mock_valkey, test_user):
    note = await create_note(db, test_user, "Followers only", visibility="followers")
    assert note.visibility == "followers"
    public = "https://www.w3.org/ns/activitystreams#Public"
    assert public not in note.to
    assert public not in note.cc


async def test_create_note_direct(db, mock_valkey, test_user):
    note = await create_note(db, test_user, "Direct message", visibility="direct")
    assert note.visibility == "direct"
    public = "https://www.w3.org/ns/activitystreams#Public"
    assert public not in note.to
    assert public not in note.cc


async def test_create_note_with_spoiler(db, mock_valkey, test_user):
    note = await create_note(
        db,
        test_user,
        "Spoilered content",
        spoiler_text="CW: spoiler",
        sensitive=True,
    )
    assert note.spoiler_text == "CW: spoiler"
    assert note.sensitive is True


async def test_create_note_with_poll(db, mock_valkey, test_user):
    note = await create_note(
        db,
        test_user,
        "Poll question?",
        poll_options=["Yes", "No"],
        poll_expires_in=3600,
    )
    assert note.is_poll is True
    assert len(note.poll_options) == 2
    assert note.poll_options[0]["title"] == "Yes"
    assert note.poll_expires_at is not None


async def test_create_note_with_poll_multiple(db, mock_valkey, test_user):
    note = await create_note(
        db,
        test_user,
        "Multi poll?",
        poll_options=["A", "B", "C"],
        poll_multiple=True,
    )
    assert note.poll_multiple is True


async def test_create_note_reply(db, mock_valkey, test_user, test_user_b):
    """Replying increments parent's replies_count."""
    parent = await create_note(db, test_user, "Parent note")
    reply = await create_note(
        db,
        test_user_b,
        "Reply to parent",
        in_reply_to_id=parent.id,
    )
    assert reply.in_reply_to_id == parent.id
    # Reload parent
    from app.services.note_service import get_note_by_id

    updated = await get_note_by_id(db, parent.id)
    assert updated.replies_count >= 1


async def test_create_note_with_hashtag(db, mock_valkey, test_user):
    note = await create_note(db, test_user, "Hello #test #nekonoverse")
    # Hashtag extraction happens in create_note
    assert note is not None
