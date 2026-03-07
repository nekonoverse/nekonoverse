import uuid
from io import BytesIO
from unittest.mock import AsyncMock, patch

# Minimal valid PNG
PNG_1x1 = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR"
    b"\x00\x00\x00\x01"
    b"\x00\x00\x00\x01"
    b"\x08\x02"
    b"\x00\x00\x00"
    b"\x90wS\xde"
)


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_media_v1(mock_s3, authed_client, test_user):
    mock_s3.return_value = "etag"
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["type"] == "image"
    assert "url" in data
    assert data["id"]


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_media_v2(mock_s3, authed_client, test_user):
    mock_s3.return_value = "etag"
    resp = await authed_client.post(
        "/api/v2/media",
        files={"file": ("test.png", BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 200
    assert resp.json()["type"] == "image"


async def test_upload_media_unauthenticated(app_client, mock_valkey):
    resp = await app_client.post(
        "/api/v1/media",
        files={"file": ("test.png", BytesIO(PNG_1x1), "image/png")},
    )
    assert resp.status_code == 401


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_media_unsupported_type(mock_s3, authed_client, test_user):
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.txt", BytesIO(b"hello"), "text/plain")},
    )
    assert resp.status_code == 422


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_get_media(mock_s3, authed_client, test_user):
    mock_s3.return_value = "etag"
    upload_resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", BytesIO(PNG_1x1), "image/png")},
    )
    file_id = upload_resp.json()["id"]
    resp = await authed_client.get(f"/api/v1/media/{file_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == file_id


async def test_get_media_not_found(app_client, mock_valkey):
    resp = await app_client.get(f"/api/v1/media/{uuid.uuid4()}")
    assert resp.status_code == 404


@patch("app.services.drive_service.delete_file", new_callable=AsyncMock)
@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_delete_media(mock_s3, mock_del, authed_client, test_user):
    mock_s3.return_value = "etag"
    upload_resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", BytesIO(PNG_1x1), "image/png")},
    )
    file_id = upload_resp.json()["id"]
    resp = await authed_client.delete(f"/api/v1/media/{file_id}")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


async def test_delete_media_unauthenticated(app_client, mock_valkey):
    resp = await app_client.delete(f"/api/v1/media/{uuid.uuid4()}")
    assert resp.status_code == 401


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_drive_files_list(mock_s3, authed_client, test_user):
    mock_s3.return_value = "etag"
    await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", BytesIO(PNG_1x1), "image/png")},
    )
    resp = await authed_client.get("/api/v1/drive/files")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert "filename" in data[0]
    assert "url" in data[0]


async def test_drive_files_unauthenticated(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/drive/files")
    assert resp.status_code == 401


@patch("app.services.drive_service.upload_file", new_callable=AsyncMock)
async def test_upload_media_with_description(mock_s3, authed_client, test_user):
    mock_s3.return_value = "etag"
    resp = await authed_client.post(
        "/api/v1/media",
        files={"file": ("test.png", BytesIO(PNG_1x1), "image/png")},
        data={"description": "A test image"},
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "A test image"
