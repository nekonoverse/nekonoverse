"""Tests for profile image deletion and focal point features."""

import io
import struct

import pytest


def _make_tiny_png() -> bytes:
    """Create a minimal valid 1x1 PNG file."""
    # PNG header
    header = b"\x89PNG\r\n\x1a\n"
    # IHDR chunk: 1x1, 8-bit RGBA
    ihdr_data = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    ihdr_crc = struct.pack(">I", 0x0D4E1CB6 & 0xFFFFFFFF)  # precomputed
    ihdr = struct.pack(">I", 13) + b"IHDR" + ihdr_data + ihdr_crc
    # IDAT chunk (minimal compressed data for 1x1 RGB)
    import zlib

    raw = b"\x00\xff\x00\x00"  # filter byte + 1 pixel RGB
    compressed = zlib.compress(raw)
    idat_crc = zlib.crc32(b"IDAT" + compressed) & 0xFFFFFFFF
    idat = struct.pack(">I", len(compressed)) + b"IDAT" + compressed + struct.pack(">I", idat_crc)
    # IEND chunk
    iend_crc = struct.pack(">I", zlib.crc32(b"IEND") & 0xFFFFFFFF)
    iend = struct.pack(">I", 0) + b"IEND" + iend_crc
    return header + ihdr + idat + iend


@pytest.fixture
def tiny_png():
    return _make_tiny_png()


class TestAvatarDelete:
    async def test_delete_avatar_clears_url(self, authed_client, test_user, db):
        """Sending avatar_delete clears the avatar URL."""
        # Set an avatar first
        test_user.actor.avatar_url = "https://example.com/old-avatar.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"avatar_delete": "1"},
        )
        assert resp.status_code == 200
        body = resp.json()
        # Default avatar path is returned when avatar_url is None
        assert body["avatar_url"] is not None
        # The actor's actual avatar_url should be cleared
        await db.refresh(test_user.actor)
        assert test_user.actor.avatar_url is None
        assert test_user.actor.avatar_file_id is None

    async def test_delete_avatar_no_effect_without_param(self, authed_client, test_user, db):
        """Not sending avatar_delete does not clear the avatar."""
        test_user.actor.avatar_url = "https://example.com/avatar.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"display_name": "Updated"},
        )
        assert resp.status_code == 200
        await db.refresh(test_user.actor)
        assert test_user.actor.avatar_url == "https://example.com/avatar.png"


class TestHeaderDelete:
    async def test_delete_header_clears_url(self, authed_client, test_user, db):
        """Sending header_delete clears the header URL."""
        test_user.actor.header_url = "https://example.com/old-header.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"header_delete": "1"},
        )
        assert resp.status_code == 200
        await db.refresh(test_user.actor)
        assert test_user.actor.header_url is None
        assert test_user.actor.header_file_id is None

    async def test_delete_header_no_effect_without_param(self, authed_client, test_user, db):
        """Not sending header_delete does not clear the header."""
        test_user.actor.header_url = "https://example.com/header.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"display_name": "Updated"},
        )
        assert resp.status_code == 200
        await db.refresh(test_user.actor)
        assert test_user.actor.header_url == "https://example.com/header.png"


class TestFocalPoint:
    async def test_focal_point_returned_in_response(self, authed_client, test_user, db):
        """Focal point data is included in user response when available."""
        from app.models.drive_file import DriveFile

        drive_file = DriveFile(
            owner_id=test_user.id,
            filename="avatar.png",
            mime_type="image/png",
            size_bytes=100,
            s3_key="test/avatar.png",
            focal_x=0.5,
            focal_y=-0.3,
        )
        db.add(drive_file)
        await db.flush()

        test_user.actor.avatar_file_id = drive_file.id
        test_user.actor.avatar_url = "https://example.com/avatar.png"
        await db.commit()

        resp = await authed_client.get("/api/v1/accounts/verify_credentials")
        assert resp.status_code == 200
        body = resp.json()
        assert body["avatar_focal"] is not None
        assert body["avatar_focal"]["x"] == pytest.approx(0.5)
        assert body["avatar_focal"]["y"] == pytest.approx(-0.3)

    async def test_focal_point_null_when_no_drive_file(self, authed_client, test_user):
        """Focal point is null when no drive file is linked."""
        resp = await authed_client.get("/api/v1/accounts/verify_credentials")
        assert resp.status_code == 200
        body = resp.json()
        assert body["avatar_focal"] is None
        assert body["header_focal"] is None

    async def test_set_header_focal_point(self, authed_client, test_user, db):
        """Setting header_focus updates the DriveFile's focal point."""
        from app.models.drive_file import DriveFile

        drive_file = DriveFile(
            owner_id=test_user.id,
            filename="header.png",
            mime_type="image/png",
            size_bytes=100,
            s3_key="test/header.png",
        )
        db.add(drive_file)
        await db.flush()

        test_user.actor.header_file_id = drive_file.id
        test_user.actor.header_url = "https://example.com/header.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"header_focus": "0.25,-0.75"},
        )
        assert resp.status_code == 200

        await db.refresh(drive_file)
        assert drive_file.focal_x == pytest.approx(0.25)
        assert drive_file.focal_y == pytest.approx(-0.75)

    async def test_set_avatar_focal_point(self, authed_client, test_user, db):
        """Setting avatar_focus updates the DriveFile's focal point."""
        from app.models.drive_file import DriveFile

        drive_file = DriveFile(
            owner_id=test_user.id,
            filename="avatar.png",
            mime_type="image/png",
            size_bytes=100,
            s3_key="test/avatar.png",
        )
        db.add(drive_file)
        await db.flush()

        test_user.actor.avatar_file_id = drive_file.id
        test_user.actor.avatar_url = "https://example.com/avatar.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"avatar_focus": "-0.5,0.8"},
        )
        assert resp.status_code == 200

        await db.refresh(drive_file)
        assert drive_file.focal_x == pytest.approx(-0.5)
        assert drive_file.focal_y == pytest.approx(0.8)

    async def test_invalid_focal_point_ignored(self, authed_client, test_user, db):
        """Invalid focal point string is silently ignored."""
        from app.models.drive_file import DriveFile

        drive_file = DriveFile(
            owner_id=test_user.id,
            filename="header.png",
            mime_type="image/png",
            size_bytes=100,
            s3_key="test/header.png",
        )
        db.add(drive_file)
        await db.flush()

        test_user.actor.header_file_id = drive_file.id
        test_user.actor.header_url = "https://example.com/header.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"header_focus": "invalid"},
        )
        assert resp.status_code == 200

        await db.refresh(drive_file)
        assert drive_file.focal_x is None
        assert drive_file.focal_y is None

    async def test_focal_point_clamped_to_range(self, authed_client, test_user, db):
        """Focal point values outside [-1, 1] are clamped."""
        from app.models.drive_file import DriveFile

        drive_file = DriveFile(
            owner_id=test_user.id,
            filename="header.png",
            mime_type="image/png",
            size_bytes=100,
            s3_key="test/header.png",
        )
        db.add(drive_file)
        await db.flush()

        test_user.actor.header_file_id = drive_file.id
        test_user.actor.header_url = "https://example.com/header.png"
        await db.commit()

        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"header_focus": "5.0,-3.0"},
        )
        assert resp.status_code == 200

        await db.refresh(drive_file)
        assert drive_file.focal_x == pytest.approx(1.0)
        assert drive_file.focal_y == pytest.approx(-1.0)

    async def test_focal_point_without_drive_file_ignored(self, authed_client, test_user):
        """Setting focal point without a linked DriveFile is silently ignored."""
        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"header_focus": "0.5,0.5"},
        )
        assert resp.status_code == 200

    async def test_upload_then_delete_avatar(self, authed_client, test_user, db, tiny_png):
        """Upload avatar then delete it — avatar returns to default."""
        from unittest.mock import AsyncMock, patch

        with patch("app.services.drive_service.upload_file", new_callable=AsyncMock):
            resp = await authed_client.patch(
                "/api/v1/accounts/update_credentials",
                files={"avatar": ("test.png", io.BytesIO(tiny_png), "image/png")},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["avatar_url"] is not None

        # Now delete
        resp = await authed_client.patch(
            "/api/v1/accounts/update_credentials",
            data={"avatar_delete": "1"},
        )
        assert resp.status_code == 200
        await db.refresh(test_user.actor)
        assert test_user.actor.avatar_url is None
