"""Tests for storage quota."""

import uuid

import pytest

from app.models.drive_file import DriveFile
from app.models.role import Role
from app.services.quota_service import check_quota, get_storage_usage


@pytest.fixture
async def seed_roles(db):
    """Seed the three built-in roles."""
    for name, display_name, is_admin, quota, priority in [
        ("user", "User", False, 1073741824, 0),
        ("moderator", "Moderator", False, 5368709120, 50),
        ("admin", "Admin", True, 0, 100),
    ]:
        role = Role(
            name=name,
            display_name=display_name,
            permissions={},
            is_admin=is_admin,
            quota_bytes=quota,
            priority=priority,
            is_system=True,
        )
        db.add(role)
    await db.flush()


async def test_storage_usage_empty(db, test_user):
    usage = await get_storage_usage(db, test_user.id)
    assert usage == 0


async def test_storage_usage_with_files(db, test_user):
    for i in range(3):
        df = DriveFile(
            id=uuid.uuid4(),
            owner_id=test_user.id,
            s3_key=f"u/{test_user.id}/test{i}.jpg",
            filename=f"test{i}.jpg",
            mime_type="image/jpeg",
            size_bytes=1000 * (i + 1),
            server_file=False,
        )
        db.add(df)
    await db.flush()

    usage = await get_storage_usage(db, test_user.id)
    assert usage == 1000 + 2000 + 3000  # 6000 bytes


async def test_server_files_not_counted(db, test_user):
    df = DriveFile(
        id=uuid.uuid4(),
        owner_id=test_user.id,
        s3_key=f"server/icon.png",
        filename="icon.png",
        mime_type="image/png",
        size_bytes=5000,
        server_file=True,
    )
    db.add(df)
    await db.flush()

    usage = await get_storage_usage(db, test_user.id)
    assert usage == 0


async def test_check_quota_within_limit(db, test_user, seed_roles):
    ok, usage, limit = await check_quota(db, test_user, 1000)
    assert ok is True
    assert usage == 0
    assert limit == 1073741824  # 1 GB


async def test_check_quota_exceeded(db, test_user, seed_roles):
    # Add a file that nearly fills the quota
    df = DriveFile(
        id=uuid.uuid4(),
        owner_id=test_user.id,
        s3_key=f"u/{test_user.id}/big.jpg",
        filename="big.jpg",
        mime_type="image/jpeg",
        size_bytes=1073741824,  # exactly 1 GB
        server_file=False,
    )
    db.add(df)
    await db.flush()

    ok, usage, limit = await check_quota(db, test_user, 1)
    assert ok is False
    assert usage == 1073741824


async def test_check_quota_admin_unlimited(db, test_user, seed_roles):
    test_user.role = "admin"
    ok, usage, limit = await check_quota(db, test_user, 999999999999)
    assert ok is True
    assert limit == 0  # unlimited


async def test_storage_endpoint(authed_client, db, seed_roles, mock_valkey):
    resp = await authed_client.get("/api/v1/accounts/storage")
    assert resp.status_code == 200
    data = resp.json()
    assert "usage_bytes" in data
    assert "quota_bytes" in data
    assert "usage_percent" in data
    assert data["usage_bytes"] == 0
    assert data["quota_bytes"] == 1073741824
