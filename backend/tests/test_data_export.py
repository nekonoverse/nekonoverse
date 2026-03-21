"""Tests for user data export."""

from unittest.mock import AsyncMock, patch

from sqlalchemy import select

from app.models.data_export import DataExport


async def test_start_export_requires_auth(app_client):
    """POST /export requires authentication."""
    resp = await app_client.post("/api/v1/export")
    assert resp.status_code in (401, 403)


async def test_start_export_creates_record(authed_client, test_user, db):
    """Starting export should create a DataExport record and enqueue job."""
    with patch("app.services.export_queue.enqueue_export", new_callable=AsyncMock) as mock_enqueue:
        resp = await authed_client.post("/api/v1/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "id" in data

    # Verify DB record
    result = await db.execute(
        select(DataExport).where(DataExport.user_id == test_user.id)
    )
    export = result.scalar_one()
    assert export.status == "pending"
    mock_enqueue.assert_called_once_with(str(export.id))


async def test_start_export_cooldown(authed_client, test_user, db):
    """Should reject if export was requested within 24 hours."""
    # Create a recent export
    with patch("app.services.export_queue.enqueue_export", new_callable=AsyncMock):
        resp1 = await authed_client.post("/api/v1/export")
    assert resp1.status_code == 200

    # Try again
    with patch("app.services.export_queue.enqueue_export", new_callable=AsyncMock):
        resp2 = await authed_client.post("/api/v1/export")
    assert resp2.status_code == 429


async def test_get_export_status_no_export(authed_client):
    """Should return null when no export exists."""
    resp = await authed_client.get("/api/v1/export")
    assert resp.status_code == 200
    assert resp.json() is None


async def test_get_export_status(authed_client, test_user, db):
    """Should return latest export status."""
    with patch("app.services.export_queue.enqueue_export", new_callable=AsyncMock):
        await authed_client.post("/api/v1/export")

    resp = await authed_client.get("/api/v1/export")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "pending"
    assert "id" in data
    assert "created_at" in data


async def test_download_not_ready(authed_client, test_user, db):
    """Download should fail if export is not completed."""
    with patch("app.services.export_queue.enqueue_export", new_callable=AsyncMock):
        resp = await authed_client.post("/api/v1/export")

    export_id = resp.json()["id"]
    resp = await authed_client.get(f"/api/v1/export/{export_id}/download")
    assert resp.status_code == 400


async def test_download_not_found(authed_client):
    """Download should return 404 for non-existent export."""
    import uuid

    fake_id = str(uuid.uuid4())
    resp = await authed_client.get(f"/api/v1/export/{fake_id}/download")
    assert resp.status_code == 404


async def test_export_service_generates_zip(test_user, db):
    """Export service should generate a valid ZIP."""
    from unittest.mock import MagicMock
    import zipfile
    import io

    export = DataExport(user_id=test_user.id, status="processing")
    db.add(export)
    await db.commit()
    await db.refresh(export)

    with (
        patch("app.services.export_service.upload_file", new_callable=AsyncMock) as mock_upload,
        patch("app.services.export_service.download_file", new_callable=AsyncMock) as mock_dl,
    ):
        mock_upload.return_value = "etag"
        from app.services.export_service import generate_export

        await generate_export(db, export)

    assert export.status == "completed"
    assert export.s3_key is not None
    assert export.size_bytes > 0
    assert export.expires_at is not None

    # Verify the uploaded data is a valid ZIP
    uploaded_data = mock_upload.call_args[0][1]
    with zipfile.ZipFile(io.BytesIO(uploaded_data)) as zf:
        names = zf.namelist()
        assert "actor.json" in names
        assert "outbox.json" in names
        assert "following_accounts.csv" in names
        assert "followers_accounts.csv" in names
        assert "bookmarks.csv" in names
        assert "blocked_accounts.csv" in names
        assert "muted_accounts.csv" in names
