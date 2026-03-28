"""Tests for neko-search integration (search queue, API fallback)."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from tests.conftest import make_note


async def test_search_ilike_fallback(authed_client, test_user, db, mock_valkey):
    """When neko-search is disabled, falls back to ILIKE search."""
    await make_note(db, test_user.actor, content="unique_test_word in this note")

    resp = await authed_client.get("/api/v2/search?q=unique_test_word&type=statuses")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["statuses"]) >= 1
    assert any("unique_test_word" in s["content"] for s in data["statuses"])


async def test_search_neko_search_integration(authed_client, test_user, db, mock_valkey):
    """When neko-search is enabled, calls the external API."""
    note = await make_note(db, test_user.actor, content="neko search test")

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"note_ids": [str(note.id)], "total": 1}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.api.mastodon.search.settings") as mock_settings,
        patch("app.utils.http_client.make_neko_search_client", return_value=mock_client),
    ):
        mock_settings.neko_search_enabled = True
        mock_settings.neko_search_base_url = "http://neko-search:8002"
        mock_settings.server_url = "http://localhost"
        mock_settings.frontend_url = "http://localhost:3000"
        mock_settings.media_proxy_key = "test-key"

        resp = await authed_client.get("/api/v2/search?q=neko+search+test&type=statuses")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["statuses"]) >= 1


async def test_search_neko_search_fallback_on_error(authed_client, test_user, db, mock_valkey):
    """When neko-search fails, falls back to ILIKE."""
    await make_note(db, test_user.actor, content="fallback_search_test content")

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.api.mastodon.search.settings") as mock_settings,
        patch("app.utils.http_client.make_neko_search_client", return_value=mock_client),
    ):
        mock_settings.neko_search_enabled = True
        mock_settings.neko_search_base_url = "http://neko-search:8002"
        mock_settings.server_url = "http://localhost"
        mock_settings.frontend_url = "http://localhost:3000"
        mock_settings.media_proxy_key = "test-key"

        resp = await authed_client.get("/api/v2/search?q=fallback_search_test&type=statuses")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["statuses"]) >= 1


async def test_search_resolve_remote_note_url(authed_client, test_user, db, mock_valkey):
    """Resolve an unknown remote note URL via search with resolve=true."""
    from tests.conftest import make_remote_actor

    actor = await make_remote_actor(db, username="resolvetest", domain="resolve.example")
    ap_id = "https://resolve.example/notes/999"

    ap_note = {
        "type": "Note",
        "id": ap_id,
        "attributedTo": actor.ap_id,
        "content": "<p>Resolved note content</p>",
        "to": ["https://www.w3.org/ns/activitystreams#Public"],
        "cc": [f"{actor.ap_id}/followers"],
        "sensitive": False,
        "published": "2026-01-01T00:00:00Z",
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = ap_note

    with patch(
        "app.services.actor_service._signed_get",
        new_callable=AsyncMock,
        return_value=mock_resp,
    ):
        resp = await authed_client.get(
            f"/api/v2/search?q={ap_id}&resolve=true&type=statuses"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert len(data["statuses"]) == 1
    assert "Resolved note content" in data["statuses"][0]["content"]


async def test_search_resolve_excludes_direct_note(authed_client, test_user, db, mock_valkey):
    """Resolve by AP URL must not return direct-visibility notes (IDOR prevention)."""
    note = await make_note(
        db, test_user.actor, content="secret DM content", visibility="direct"
    )
    # Override ap_id to https:// so the resolve path is triggered
    note.ap_id = f"https://localhost/notes/{note.id}"
    await db.flush()

    resp = await authed_client.get(
        f"/api/v2/search?q={note.ap_id}&resolve=true&type=statuses"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["statuses"]) == 0, "direct note must not be returned via resolve"


async def test_search_resolve_excludes_followers_note(authed_client, test_user, db, mock_valkey):
    """Resolve by AP URL must not return followers-only notes (IDOR prevention)."""
    note = await make_note(
        db, test_user.actor, content="followers only content", visibility="followers"
    )
    note.ap_id = f"https://localhost/notes/{note.id}"
    await db.flush()

    resp = await authed_client.get(
        f"/api/v2/search?q={note.ap_id}&resolve=true&type=statuses"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["statuses"]) == 0, "followers note must not be returned via resolve"


async def test_search_resolve_allows_unlisted_note(authed_client, test_user, db, mock_valkey):
    """Resolve by AP URL should return unlisted notes."""
    note = await make_note(
        db, test_user.actor, content="unlisted resolve test", visibility="unlisted"
    )
    note.ap_id = f"https://localhost/notes/{note.id}"
    await db.flush()

    resp = await authed_client.get(
        f"/api/v2/search?q={note.ap_id}&resolve=true&type=statuses"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["statuses"]) == 1, "unlisted note should be returned via resolve"


async def test_search_empty_query(authed_client, mock_valkey):
    """Empty query returns 422."""
    resp = await authed_client.get("/api/v2/search?q=")
    assert resp.status_code == 422


async def test_suggest_proxy(authed_client, mock_valkey):
    """When neko-search is enabled, /suggest proxies to neko-search."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "suggestions": [{"token": "ねこ", "df": 42}],
        "prefix": "ねこ",
    }
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.api.mastodon.search.settings") as mock_settings,
        patch("app.utils.http_client.make_neko_search_client", return_value=mock_client),
    ):
        mock_settings.neko_search_enabled = True
        mock_settings.neko_search_base_url = "http://neko-search:8002"

        resp = await authed_client.get("/api/v2/search/suggest?q=ねこ")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["suggestions"]) == 1
        assert data["suggestions"][0]["token"] == "ねこ"
        assert data["prefix"] == "ねこ"


async def test_suggest_disabled(authed_client, mock_valkey):
    """When neko-search is disabled, /suggest returns empty."""
    with patch("app.api.mastodon.search.settings") as mock_settings:
        mock_settings.neko_search_enabled = False

        resp = await authed_client.get("/api/v2/search/suggest?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggestions"] == []


async def test_suggest_fallback_on_error(authed_client, mock_valkey):
    """When neko-search fails, /suggest returns empty."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.api.mastodon.search.settings") as mock_settings,
        patch("app.utils.http_client.make_neko_search_client", return_value=mock_client),
    ):
        mock_settings.neko_search_enabled = True
        mock_settings.neko_search_base_url = "http://neko-search:8002"

        resp = await authed_client.get("/api/v2/search/suggest?q=test")
        assert resp.status_code == 200
        data = resp.json()
        assert data["suggestions"] == []


async def test_search_queue_enqueue_index(mock_valkey):
    """enqueue_index pushes job to Valkey."""
    import uuid

    from datetime import datetime, timezone

    with patch("app.services.search_queue.settings") as mock_settings:
        mock_settings.neko_search_enabled = True

        mock_valkey_client = AsyncMock()
        with patch("app.services.search_queue.valkey_client", mock_valkey_client):
            from app.services.search_queue import enqueue_index

            note_id = uuid.uuid4()
            published = datetime.now(timezone.utc)
            await enqueue_index(note_id, "test content", published)

            mock_valkey_client.lpush.assert_called_once()
            call_args = mock_valkey_client.lpush.call_args
            assert call_args[0][0] == "neko_search:queue"
            job = json.loads(call_args[0][1])
            assert job["type"] == "index"
            assert job["note_id"] == str(note_id)
            assert job["text"] == "test content"


async def test_search_queue_enqueue_delete(mock_valkey):
    """enqueue_delete pushes delete job to Valkey."""
    import uuid

    with patch("app.services.search_queue.settings") as mock_settings:
        mock_settings.neko_search_enabled = True

        mock_valkey_client = AsyncMock()
        with patch("app.services.search_queue.valkey_client", mock_valkey_client):
            from app.services.search_queue import enqueue_delete

            note_id = uuid.uuid4()
            await enqueue_delete(note_id)

            mock_valkey_client.lpush.assert_called_once()
            call_args = mock_valkey_client.lpush.call_args
            assert call_args[0][0] == "neko_search:queue"
            job = json.loads(call_args[0][1])
            assert job["type"] == "delete"
            assert job["note_id"] == str(note_id)


async def test_search_queue_disabled(mock_valkey):
    """When neko-search is disabled, enqueue does nothing."""
    import uuid

    from datetime import datetime, timezone

    with patch("app.services.search_queue.settings") as mock_settings:
        mock_settings.neko_search_enabled = False

        mock_valkey_client = AsyncMock()
        with patch("app.services.search_queue.valkey_client", mock_valkey_client):
            from app.services.search_queue import enqueue_delete, enqueue_index

            await enqueue_index(uuid.uuid4(), "test", datetime.now(timezone.utc))
            await enqueue_delete(uuid.uuid4())

            mock_valkey_client.lpush.assert_not_called()
