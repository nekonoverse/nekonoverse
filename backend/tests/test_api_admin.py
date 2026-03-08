"""Tests for admin API endpoints: server icon, emoji CRUD, import/export, server files."""

import io
import json
import zipfile
from unittest.mock import AsyncMock, patch

import pytest

from tests.conftest import make_remote_actor

PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x00\x01"
    b"\x08\x02"
    b"\x00\x00\x00"
    b"\x90wS\xde"
)


# ── Helpers ─────────────────────────────────────────────────────────────


async def make_admin(db, mock_valkey, app_client, *, username="adminuser"):
    from app.services.user_service import create_user
    user = await create_user(db, username, f"{username}@example.com", "password1234", role="admin")
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "admin-session")
    return user


async def make_regular(db, mock_valkey, app_client, *, username="regularuser"):
    from app.services.user_service import create_user
    user = await create_user(db, username, f"{username}@example.com", "password1234")
    mock_valkey.get = AsyncMock(return_value=str(user.id))
    app_client.cookies.set("nekonoverse_session", "user-session")
    return user


# ── Server Icon ─────────────────────────────────────────────────────────


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_server_icon_as_admin(mock_s3, app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    mock_s3.return_value = "etag"

    resp = await app_client.post(
        "/api/v1/admin/server-icon",
        files={"file": ("icon.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "url" in data


async def test_upload_server_icon_non_admin(app_client, db, mock_valkey):
    await make_regular(db, mock_valkey, app_client)
    resp = await app_client.post(
        "/api/v1/admin/server-icon",
        files={"file": ("icon.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 403


async def test_upload_server_icon_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post(
        "/api/v1/admin/server-icon",
        files={"file": ("icon.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 401


# ── Emoji List ──────────────────────────────────────────────────────────


async def test_emoji_list_empty(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    resp = await app_client.get("/api/v1/admin/emoji/list")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_emoji_list_returns_local_emojis(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)

    from app.services.emoji_service import create_local_emoji
    await create_local_emoji(db, "test_cat", "http://localhost/emoji/test_cat.png", category="cats")
    await db.flush()

    resp = await app_client.get("/api/v1/admin/emoji/list")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["shortcode"] == "test_cat"
    assert data[0]["category"] == "cats"


async def test_emoji_list_forbidden_non_admin(app_client, db, mock_valkey):
    await make_regular(db, mock_valkey, app_client)
    resp = await app_client.get("/api/v1/admin/emoji/list")
    assert resp.status_code == 403


# ── Emoji Add ───────────────────────────────────────────────────────────


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_emoji_add(mock_s3, app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    mock_s3.return_value = "etag"

    resp = await app_client.post(
        "/api/v1/admin/emoji/add",
        data={
            "shortcode": "neko_smile",
            "category": "neko",
            "aliases": '["smile", "happy"]',
            "license": "CC-BY-4.0",
            "author": "neko_artist",
            "is_sensitive": "false",
        },
        files={"file": ("neko.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["shortcode"] == "neko_smile"
    assert data["category"] == "neko"
    assert data["aliases"] == ["smile", "happy"]
    assert data["license"] == "CC-BY-4.0"
    assert data["author"] == "neko_artist"


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_emoji_add_duplicate_409(mock_s3, app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    mock_s3.return_value = "etag"

    from app.services.emoji_service import create_local_emoji
    await create_local_emoji(db, "dup_emoji", "http://localhost/emoji/dup.png")
    await db.flush()

    resp = await app_client.post(
        "/api/v1/admin/emoji/add",
        data={"shortcode": "dup_emoji"},
        files={"file": ("dup.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 409


# ── Emoji Update ────────────────────────────────────────────────────────


async def test_emoji_update(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)

    from app.services.emoji_service import create_local_emoji
    emoji = await create_local_emoji(db, "upd_emoji", "http://localhost/emoji/upd.png")
    await db.flush()

    resp = await app_client.patch(
        f"/api/v1/admin/emoji/{emoji.id}",
        json={"category": "updated", "license": "MIT"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["category"] == "updated"
    assert data["license"] == "MIT"


async def test_emoji_update_not_found(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    import uuid
    resp = await app_client.patch(
        f"/api/v1/admin/emoji/{uuid.uuid4()}",
        json={"category": "x"},
    )
    assert resp.status_code == 404


# ── Emoji Delete ────────────────────────────────────────────────────────


async def test_emoji_delete(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)

    from app.services.emoji_service import create_local_emoji
    emoji = await create_local_emoji(db, "del_emoji", "http://localhost/emoji/del.png")
    await db.flush()

    resp = await app_client.delete(f"/api/v1/admin/emoji/{emoji.id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    # Verify deleted
    resp2 = await app_client.get("/api/v1/admin/emoji/list")
    shortcodes = [e["shortcode"] for e in resp2.json()]
    assert "del_emoji" not in shortcodes


async def test_emoji_delete_not_found(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    import uuid
    resp = await app_client.delete(f"/api/v1/admin/emoji/{uuid.uuid4()}")
    assert resp.status_code == 404


# ── Emoji Import ────────────────────────────────────────────────────────


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_emoji_import(mock_s3, app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    mock_s3.return_value = "etag"

    # Build a ZIP with meta.json + image
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        meta = {
            "metaVersion": 2,
            "host": "remote.example",
            "emojis": [
                {
                    "downloaded": True,
                    "fileName": "imported_cat.png",
                    "emoji": {
                        "name": "imported_cat",
                        "category": "imported",
                        "aliases": ["cat"],
                        "license": "CC0",
                        "author": "someone",
                        "copyPermission": "allow",
                    },
                },
                {
                    "downloaded": False,
                    "fileName": "skipped.png",
                    "emoji": {"name": "skipped"},
                },
            ],
        }
        zf.writestr("meta.json", json.dumps(meta))
        zf.writestr("imported_cat.png", PNG_1x1)
    buf.seek(0)

    resp = await app_client.post(
        "/api/v1/admin/emoji/import",
        files={"file": ("emojis.zip", buf, "application/zip")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["imported"] == 1
    assert data["skipped"] == 1

    # Verify the imported emoji exists
    from app.services.emoji_service import get_custom_emoji
    emoji = await get_custom_emoji(db, "imported_cat", None)
    assert emoji is not None
    assert emoji.license == "CC0"
    assert emoji.author == "someone"
    assert emoji.import_from == "remote.example"


async def test_emoji_import_invalid_zip(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    resp = await app_client.post(
        "/api/v1/admin/emoji/import",
        files={"file": ("bad.zip", io.BytesIO(b"not a zip"), "application/zip")},
    )
    assert resp.status_code == 422


# ── Emoji Export ────────────────────────────────────────────────────────


@patch("app.storage.get_file_stream", new_callable=AsyncMock)
async def test_emoji_export(mock_stream, app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)

    from app.models.drive_file import DriveFile
    df = DriveFile(
        filename="test_export.png", mime_type="image/png",
        size_bytes=len(PNG_1x1), s3_key="server/test_export.png",
        server_file=True,
    )
    db.add(df)
    await db.flush()

    from app.services.emoji_service import create_local_emoji
    await create_local_emoji(
        db, "export_cat", f"http://localhost/media/{df.id}",
        drive_file_id=df.id, category="export_test",
    )
    await db.flush()

    # Mock get_file_stream to return PNG data
    async def fake_chunks():
        yield PNG_1x1
    mock_stream.return_value = (fake_chunks(), "image/png", len(PNG_1x1))

    resp = await app_client.get("/api/v1/admin/emoji/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"

    # Parse the returned ZIP
    zbuf = io.BytesIO(resp.content)
    with zipfile.ZipFile(zbuf) as zf:
        assert "meta.json" in zf.namelist()
        meta = json.loads(zf.read("meta.json"))
        assert meta["metaVersion"] == 2
        shortcodes = [e["emoji"]["name"] for e in meta["emojis"]]
        assert "export_cat" in shortcodes


# ── Server Files ────────────────────────────────────────────────────────


async def test_server_files_list_empty(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    resp = await app_client.get("/api/v1/admin/server-files")
    assert resp.status_code == 200
    assert resp.json() == []


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_server_file_upload(mock_s3, app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    mock_s3.return_value = "etag"

    resp = await app_client.post(
        "/api/v1/admin/server-files",
        files={"file": ("test.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "id" in data
    assert data["filename"] == "test.png"
    assert data["mime_type"] == "image/png"


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
@patch("app.services.drive_service.delete_file", new_callable=AsyncMock)
async def test_server_file_delete(mock_del, mock_s3, app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    mock_s3.return_value = "etag"

    # Upload first
    resp = await app_client.post(
        "/api/v1/admin/server-files",
        files={"file": ("todel.png", io.BytesIO(PNG_1x1), "image/png")},
    )
    file_id = resp.json()["id"]

    resp = await app_client.delete(f"/api/v1/admin/server-files/{file_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_server_file_delete_not_found(app_client, db, mock_valkey):
    await make_admin(db, mock_valkey, app_client)
    import uuid
    resp = await app_client.delete(f"/api/v1/admin/server-files/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_server_files_forbidden_non_admin(app_client, db, mock_valkey):
    await make_regular(db, mock_valkey, app_client)
    resp = await app_client.get("/api/v1/admin/server-files")
    assert resp.status_code == 403
