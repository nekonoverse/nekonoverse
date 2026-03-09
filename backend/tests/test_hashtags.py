import uuid
from unittest.mock import AsyncMock, patch

from tests.conftest import make_note, make_remote_actor

from app.services.hashtag_service import (
    extract_hashtags,
    extract_hashtags_from_ap_tags,
    get_hashtags_for_note,
    get_notes_by_hashtag,
    get_trending_tags,
    upsert_hashtags,
)


class TestExtractHashtags:
    def test_basic_extraction(self):
        text = "Hello #world! This is a #test post."
        assert extract_hashtags(text) == ["world", "test"]

    def test_no_hashtags(self):
        text = "Hello world! No tags here."
        assert extract_hashtags(text) == []

    def test_duplicate_hashtags(self):
        text = "#hello #Hello #HELLO"
        assert extract_hashtags(text) == ["hello"]

    def test_japanese_hashtags(self):
        text = "こんにちは #ねこ #猫 #cat"
        assert extract_hashtags(text) == ["ねこ", "猫", "cat"]

    def test_underscore_in_hashtags(self):
        text = "#hello_world #test_123"
        assert extract_hashtags(text) == ["hello_world", "test_123"]

    def test_mixed_case_lowered(self):
        text = "#CamelCase #UPPER"
        assert extract_hashtags(text) == ["camelcase", "upper"]

    def test_katakana_hashtags(self):
        text = "#ネコ is a cat"
        assert extract_hashtags(text) == ["ネコ"]


class TestExtractHashtagsFromApTags:
    def test_basic(self):
        tags = [
            {"type": "Hashtag", "name": "#hello", "href": "https://example.com/tags/hello"},
            {"type": "Mention", "name": "@user", "href": "https://example.com/users/user"},
            {"type": "Hashtag", "name": "#world", "href": "https://example.com/tags/world"},
        ]
        assert extract_hashtags_from_ap_tags(tags) == ["hello", "world"]

    def test_empty(self):
        assert extract_hashtags_from_ap_tags([]) == []

    def test_no_hash_prefix(self):
        tags = [{"type": "Hashtag", "name": "test"}]
        assert extract_hashtags_from_ap_tags(tags) == ["test"]

    def test_deduplication(self):
        tags = [
            {"type": "Hashtag", "name": "#Hello"},
            {"type": "Hashtag", "name": "#hello"},
        ]
        assert extract_hashtags_from_ap_tags(tags) == ["hello"]


class TestUpsertHashtags:
    async def test_create_new_hashtags(self, db):
        note_id = uuid.uuid4()
        # Create a dummy note first
        actor = await make_remote_actor(db, username="taguser1")
        note = await make_note(db, actor, content="test #hello", local=False)

        await upsert_hashtags(db, note.id, ["hello", "world"])

        tags = await get_hashtags_for_note(db, note.id)
        assert sorted(tags) == ["hello", "world"]

    async def test_update_usage_count(self, db):
        actor = await make_remote_actor(db, username="taguser2")
        note1 = await make_note(db, actor, content="test #counting")
        await upsert_hashtags(db, note1.id, ["counting"])

        note2 = await make_note(db, actor, content="another #counting")
        await upsert_hashtags(db, note2.id, ["counting"])

        trending = await get_trending_tags(db, limit=50)
        counting_tag = next((t for t in trending if t.name == "counting"), None)
        assert counting_tag is not None
        assert counting_tag.usage_count == 2

    async def test_no_duplicate_associations(self, db):
        actor = await make_remote_actor(db, username="taguser3")
        note = await make_note(db, actor, content="test #unique")

        await upsert_hashtags(db, note.id, ["unique"])
        await upsert_hashtags(db, note.id, ["unique"])

        tags = await get_hashtags_for_note(db, note.id)
        assert tags == ["unique"]


class TestGetNotesByHashtag:
    async def test_returns_matching_notes(self, db):
        actor = await make_remote_actor(db, username="taguser4")
        note1 = await make_note(db, actor, content="First #findme post")
        await upsert_hashtags(db, note1.id, ["findme"])

        note2 = await make_note(db, actor, content="Second #other post")
        await upsert_hashtags(db, note2.id, ["other"])

        results = await get_notes_by_hashtag(db, "findme")
        assert len(results) == 1
        assert results[0].id == note1.id

    async def test_case_insensitive(self, db):
        actor = await make_remote_actor(db, username="taguser5")
        note = await make_note(db, actor, content="test #CaseTest")
        await upsert_hashtags(db, note.id, ["casetest"])

        results = await get_notes_by_hashtag(db, "CaseTest")
        assert len(results) == 1

    async def test_excludes_deleted_notes(self, db):
        from datetime import datetime, timezone
        actor = await make_remote_actor(db, username="taguser6")
        note = await make_note(db, actor, content="deleted #gonetag")
        await upsert_hashtags(db, note.id, ["gonetag"])
        note.deleted_at = datetime.now(timezone.utc)
        await db.flush()

        results = await get_notes_by_hashtag(db, "gonetag")
        assert len(results) == 0


class TestGetTrendingTags:
    async def test_returns_ordered_by_usage(self, db):
        actor = await make_remote_actor(db, username="taguser7")

        for i in range(3):
            n = await make_note(db, actor, content=f"popular #{i} #popular")
            await upsert_hashtags(db, n.id, ["popular"])

        for i in range(1):
            n = await make_note(db, actor, content=f"less #{i} #less")
            await upsert_hashtags(db, n.id, ["less"])

        trending = await get_trending_tags(db, limit=2)
        assert len(trending) >= 1
        # "popular" should be first since it has highest usage_count
        names = [t.name for t in trending]
        if "popular" in names and "less" in names:
            assert names.index("popular") < names.index("less")


class TestTagTimelineEndpoint:
    async def test_tag_timeline(self, app_client, db, test_user, mock_valkey):
        # Create a note with a hashtag via API
        resp = await app_client.post(
            "/api/v1/statuses",
            json={"content": "Hello #testendpoint", "visibility": "public"},
        )
        assert resp.status_code == 201

        # Fetch tag timeline
        resp = await app_client.get("/api/v1/timelines/tag/testendpoint")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any("testendpoint" in n.get("content", "").lower() for n in data)

    async def test_tag_timeline_empty(self, app_client, db, mock_valkey):
        resp = await app_client.get("/api/v1/timelines/tag/nonexistenttag99")
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    async def test_trending_tags_endpoint(self, app_client, db, test_user, mock_valkey):
        # Create some notes with hashtags
        for i in range(3):
            await app_client.post(
                "/api/v1/statuses",
                json={"content": f"Trending #{i} #trendtest", "visibility": "public"},
            )

        resp = await app_client.get("/api/v1/trends/tags")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)

    async def test_note_response_includes_tags(self, app_client, db, test_user, mock_valkey):
        resp = await app_client.post(
            "/api/v1/statuses",
            json={"content": "Check tags #tagresponse", "visibility": "public"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert "tags" in data
        assert any(t["name"] == "tagresponse" for t in data["tags"])
