from unittest.mock import AsyncMock, patch, MagicMock

from app import VERSION as __version__
from tests.conftest import make_note


async def test_nodeinfo_discovery(app_client):
    resp = await app_client.get("/.well-known/nodeinfo")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["links"]) == 1
    link = data["links"][0]
    assert link["rel"] == "http://nodeinfo.diaspora.software/ns/schema/2.0"
    assert link["href"].endswith("/nodeinfo/2.0")


async def test_nodeinfo(app_client):
    resp = await app_client.get("/nodeinfo/2.0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == "2.0"
    assert data["software"]["name"] == "nekonoverse"
    assert data["protocols"] == ["activitypub"]
    assert "usage" in data
    assert "users" in data["usage"]
    assert "localPosts" in data["usage"]


async def test_nodeinfo_version_from_init(app_client):
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["software"]["version"] == __version__


async def test_nodeinfo_user_count(app_client, test_user):
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["usage"]["users"]["total"] >= 1


async def test_nodeinfo_active_users(app_client, test_user, db):
    await make_note(db, test_user.actor, content="active user note")
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["usage"]["users"]["activeHalfyear"] >= 1
    assert data["usage"]["users"]["activeMonth"] >= 1


async def test_nodeinfo_post_count(app_client, test_user, db):
    await make_note(db, test_user.actor, content="nodeinfo test note")
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["usage"]["localPosts"] >= 1


async def test_nodeinfo_open_registrations_default(app_client):
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert isinstance(data["openRegistrations"], bool)


async def test_nodeinfo_registration_closed(app_client, db):
    from app.services.server_settings_service import set_setting
    await set_setting(db, "registration_mode", "closed")
    await db.commit()

    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["openRegistrations"] is False


async def test_nodeinfo_metadata(app_client):
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["metadata"]["nodeName"] == "Nekonoverse"
    assert "emoji_reactions" in data["metadata"]["features"]


async def test_nodeinfo_custom_server_name(app_client, db):
    from app.services.server_settings_service import set_setting
    await set_setting(db, "server_name", "My Custom Server")
    await db.commit()
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["metadata"]["nodeName"] == "My Custom Server"


async def test_nodeinfo_custom_description(app_client, db):
    from app.services.server_settings_service import set_setting
    await set_setting(db, "server_description", "Custom description")
    await db.commit()
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["metadata"]["nodeDescription"] == "Custom description"


async def test_nodeinfo_icon_url(app_client, db):
    from app.services.server_settings_service import set_setting
    await set_setting(db, "server_icon_url", "https://example.com/icon.png")
    await db.commit()
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["metadata"]["iconUrl"] == "https://example.com/icon.png"


async def test_nodeinfo_theme_color(app_client, db):
    from app.services.server_settings_service import set_setting
    await set_setting(db, "server_theme_color", "#ff6600")
    await db.commit()
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["metadata"]["themeColor"] == "#ff6600"


async def test_nodeinfo_registration_open_via_setting(app_client, db):
    from app.services.server_settings_service import set_setting
    await set_setting(db, "registration_mode", "open")
    await db.commit()
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["openRegistrations"] is True


async def test_nodeinfo_registration_open_legacy(app_client, db):
    from app.services.server_settings_service import set_setting
    await set_setting(db, "registration_open", "true")
    await db.commit()
    resp = await app_client.get("/nodeinfo/2.0")
    data = resp.json()
    assert data["openRegistrations"] is True


async def test_fetch_software_extracts_instance_name():
    """_fetch_software should return (name, version, instance_name)."""
    from app.utils.nodeinfo import _fetch_software

    nodeinfo_resp = {
        "software": {"name": "Misskey", "version": "2024.5.0"},
        "metadata": {"nodeName": "ねこのみすきー"},
    }
    wellknown_resp = {
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": "https://example.com/nodeinfo/2.0",
            }
        ]
    }

    mock_responses = {}

    class FakeResponse:
        def __init__(self, data):
            self.status_code = 200
            self._data = data

        def json(self):
            return self._data

    async def fake_get(url, **kwargs):
        if "well-known" in url:
            return FakeResponse(wellknown_resp)
        return FakeResponse(nodeinfo_resp)

    with patch("app.utils.nodeinfo.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get = fake_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        name, version, instance_name = await _fetch_software("example.com")

    assert name == "misskey"
    assert version == "2024.5.0"
    assert instance_name == "ねこのみすきー"


async def test_fetch_software_no_node_name():
    """_fetch_software returns None for instance_name when not in metadata."""
    from app.utils.nodeinfo import _fetch_software

    nodeinfo_resp = {
        "software": {"name": "Mastodon", "version": "4.2.0"},
        "metadata": {},
    }
    wellknown_resp = {
        "links": [
            {
                "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                "href": "https://example.com/nodeinfo/2.0",
            }
        ]
    }

    class FakeResponse:
        def __init__(self, data):
            self.status_code = 200
            self._data = data

        def json(self):
            return self._data

    async def fake_get(url, **kwargs):
        if "well-known" in url:
            return FakeResponse(wellknown_resp)
        return FakeResponse(nodeinfo_resp)

    with patch("app.utils.nodeinfo.httpx.AsyncClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.get = fake_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        name, version, instance_name = await _fetch_software("example.com")

    assert name == "mastodon"
    assert version == "4.2.0"
    assert instance_name is None
