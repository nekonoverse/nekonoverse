"""Tests for the bookmark service layer."""

import asyncio
from datetime import datetime, timezone

import pytest

from app.services.bookmark_service import (
    create_bookmark,
    get_bookmarks,
    is_bookmarked,
    remove_bookmark,
)
from tests.conftest import make_note


async def test_create_bookmark(db, test_user):
    note = await make_note(db, test_user.actor)
    bookmark = await create_bookmark(db, test_user.actor_id, note.id)

    assert bookmark.actor_id == test_user.actor_id
    assert bookmark.note_id == note.id
    assert bookmark.id is not None
    assert bookmark.created_at is not None


async def test_create_bookmark_duplicate(db, test_user):
    note = await make_note(db, test_user.actor)
    await create_bookmark(db, test_user.actor_id, note.id)

    with pytest.raises(ValueError, match="Already bookmarked"):
        await create_bookmark(db, test_user.actor_id, note.id)


async def test_remove_bookmark(db, test_user):
    note = await make_note(db, test_user.actor)
    await create_bookmark(db, test_user.actor_id, note.id)

    await remove_bookmark(db, test_user.actor_id, note.id)

    result = await is_bookmarked(db, test_user.actor_id, note.id)
    assert result is False


async def test_remove_bookmark_not_exists(db, test_user):
    note = await make_note(db, test_user.actor)

    with pytest.raises(ValueError, match="Not bookmarked"):
        await remove_bookmark(db, test_user.actor_id, note.id)


async def test_is_bookmarked_true(db, test_user):
    note = await make_note(db, test_user.actor)
    await create_bookmark(db, test_user.actor_id, note.id)

    assert await is_bookmarked(db, test_user.actor_id, note.id) is True


async def test_is_bookmarked_false(db, test_user):
    note = await make_note(db, test_user.actor)

    assert await is_bookmarked(db, test_user.actor_id, note.id) is False


async def test_get_bookmarks_empty(db, test_user):
    result = await get_bookmarks(db, test_user.actor_id)
    assert result == []


async def test_get_bookmarks_returns_notes(db, test_user):
    note1 = await make_note(db, test_user.actor, content="First note")
    await create_bookmark(db, test_user.actor_id, note1.id)

    # created_atに差をつけるために少し待つ
    await asyncio.sleep(0.01)

    note2 = await make_note(db, test_user.actor, content="Second note")
    await create_bookmark(db, test_user.actor_id, note2.id)

    await asyncio.sleep(0.01)

    note3 = await make_note(db, test_user.actor, content="Third note")
    await create_bookmark(db, test_user.actor_id, note3.id)

    bookmarks = await get_bookmarks(db, test_user.actor_id)
    assert len(bookmarks) == 3
    # created_at descでソートされるため、最新のブックマークが先頭
    assert bookmarks[0].id == note3.id
    assert bookmarks[1].id == note2.id
    assert bookmarks[2].id == note1.id


async def test_get_bookmarks_excludes_deleted_notes(db, test_user):
    note = await make_note(db, test_user.actor, content="Will be deleted")
    await create_bookmark(db, test_user.actor_id, note.id)

    # ソフトデリートする
    note.deleted_at = datetime.now(timezone.utc)
    await db.flush()

    bookmarks = await get_bookmarks(db, test_user.actor_id)
    assert len(bookmarks) == 0


async def test_get_bookmarks_limit(db, test_user):
    for i in range(5):
        note = await make_note(db, test_user.actor, content=f"Note {i}")
        await create_bookmark(db, test_user.actor_id, note.id)
        await asyncio.sleep(0.01)

    bookmarks = await get_bookmarks(db, test_user.actor_id, limit=3)
    assert len(bookmarks) == 3
