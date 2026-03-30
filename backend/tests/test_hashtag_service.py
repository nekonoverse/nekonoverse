"""Tests for hashtag_service: extraction, upsert, lookup, trending."""

from app.services.hashtag_service import (
    extract_hashtags,
    extract_hashtags_from_ap_tags,
    get_hashtags_for_note,
    get_hashtags_for_notes,
    get_trending_tags,
    upsert_hashtags,
)
from tests.conftest import make_note, make_remote_actor

# -- extract_hashtags --


def test_extract_hashtags_basic():
    result = extract_hashtags("#hello #world")
    assert result == ["hello", "world"]


def test_extract_hashtags_unicode():
    result = extract_hashtags("#日本語 is Japanese")
    assert result == ["日本語"]


def test_extract_hashtags_empty():
    result = extract_hashtags("no tags here")
    assert result == []


# -- extract_hashtags_from_ap_tags --


def test_extract_hashtags_from_ap_tags():
    tags = [
        {"type": "Hashtag", "name": "#test", "href": "https://example.com/tags/test"},
        {"type": "Mention", "name": "@user", "href": "https://example.com/users/user"},
        {"type": "Hashtag", "name": "#hello"},
    ]
    result = extract_hashtags_from_ap_tags(tags)
    assert result == ["test", "hello"]


def test_extract_hashtags_from_ap_tags_empty():
    result = extract_hashtags_from_ap_tags([])
    assert result == []


# -- upsert_hashtags --


async def test_upsert_hashtags(db):
    actor = await make_remote_actor(db, username="tagtest1")
    note = await make_note(db, actor, content="test #hello #world")

    await upsert_hashtags(db, note.id, ["hello", "world"])

    tags = await get_hashtags_for_note(db, note.id)
    assert sorted(tags) == ["hello", "world"]


async def test_upsert_hashtags_updates_count(db):
    actor = await make_remote_actor(db, username="tagtest2")
    note1 = await make_note(db, actor, content="first #counting")
    await upsert_hashtags(db, note1.id, ["counting"])

    note2 = await make_note(db, actor, content="second #counting")
    await upsert_hashtags(db, note2.id, ["counting"])

    trending = await get_trending_tags(db, limit=50)
    counting_tag = next((t for t in trending if t.name == "counting"), None)
    assert counting_tag is not None
    assert counting_tag.usage_count == 2


# -- get_hashtags_for_note --


async def test_get_hashtags_for_note(db):
    actor = await make_remote_actor(db, username="tagtest3")
    note = await make_note(db, actor, content="test #alpha #beta")

    await upsert_hashtags(db, note.id, ["alpha", "beta"])

    tags = await get_hashtags_for_note(db, note.id)
    assert sorted(tags) == ["alpha", "beta"]


# -- get_hashtags_for_notes --


async def test_get_hashtags_for_notes_batch(db):
    actor = await make_remote_actor(db, username="tagtest4")
    note1 = await make_note(db, actor, content="first #aaa")
    note2 = await make_note(db, actor, content="second #bbb #ccc")

    await upsert_hashtags(db, note1.id, ["aaa"])
    await upsert_hashtags(db, note2.id, ["bbb", "ccc"])

    tags_map = await get_hashtags_for_notes(db, [note1.id, note2.id])

    assert "aaa" in tags_map[note1.id]
    assert sorted(tags_map[note2.id]) == ["bbb", "ccc"]


# -- get_trending_tags --


async def test_get_trending_tags_empty(db):
    trending = await get_trending_tags(db, limit=10)
    assert trending == []
