"""Tests for role management."""

import pytest

from app.models.role import Role
from app.services.role_service import (
    create_role,
    delete_role,
    get_all_roles,
    get_role,
    has_permission,
    update_role,
)


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
            permissions={"users": True, "reports": True} if name == "moderator" else {},
            is_admin=is_admin,
            quota_bytes=quota,
            priority=priority,
            is_system=True,
        )
        db.add(role)
    await db.flush()


async def test_get_all_roles(db, seed_roles):
    roles = await get_all_roles(db)
    assert len(roles) == 3
    # Should be sorted by priority desc
    assert roles[0].name == "admin"
    assert roles[1].name == "moderator"
    assert roles[2].name == "user"


async def test_get_role(db, seed_roles):
    role = await get_role(db, "moderator")
    assert role is not None
    assert role.display_name == "Moderator"
    assert role.quota_bytes == 5368709120


async def test_create_role(db, seed_roles):
    role = await create_role(db, "vip", "VIP User")
    assert role.name == "vip"
    assert role.display_name == "VIP User"
    assert role.is_system is False
    assert role.quota_bytes == 1073741824  # default


async def test_create_role_with_copy(db, seed_roles):
    role = await create_role(db, "senior_mod", "Senior Moderator", copy_from="moderator")
    assert role.permissions.get("users") is True
    assert role.quota_bytes == 5368709120


async def test_create_duplicate_role(db, seed_roles):
    with pytest.raises(ValueError, match="already exists"):
        await create_role(db, "admin", "Duplicate Admin")


async def test_update_role(db, seed_roles):
    role = await update_role(db, "moderator", display_name="Mod", quota_bytes=10737418240)
    assert role.display_name == "Mod"
    assert role.quota_bytes == 10737418240


async def test_update_nonexistent_role(db, seed_roles):
    with pytest.raises(ValueError, match="not found"):
        await update_role(db, "nonexistent", display_name="X")


async def test_delete_system_role(db, seed_roles):
    with pytest.raises(ValueError, match="built-in"):
        await delete_role(db, "admin")


async def test_delete_role_in_use(db, seed_roles, test_user):
    # Create a custom role and assign it to the test user
    await create_role(db, "temp_role", "Temp")
    test_user.role = "temp_role"
    await db.flush()
    with pytest.raises(ValueError, match="user.*assigned"):
        await delete_role(db, "temp_role")


async def test_delete_role_success(db, seed_roles):
    await create_role(db, "temp", "Temporary")
    await delete_role(db, "temp")
    assert await get_role(db, "temp") is None


async def test_has_permission_admin(db, seed_roles, test_user):
    test_user.role = "admin"
    assert await has_permission(db, test_user, "users") is True
    assert await has_permission(db, test_user, "anything") is True


async def test_has_permission_moderator(db, seed_roles, test_user):
    test_user.role = "moderator"
    assert await has_permission(db, test_user, "users") is True
    # Permission not in moderator's permission map
    assert await has_permission(db, test_user, "content") is False


async def test_has_permission_user(db, seed_roles, test_user):
    test_user.role = "user"
    assert await has_permission(db, test_user, "users") is False


async def test_custom_role_is_staff(db, seed_roles):
    from app.services.user_service import create_user

    await create_role(db, "helper", "Helper")
    user = await create_user(
        db, "helper_user", "helper@test.com", "password1234", display_name="Helper"
    )
    user.role = "helper"
    assert user.is_staff is True
    assert user.is_admin is False


# --- API endpoint tests ---


async def test_api_list_roles(authed_client, db, seed_roles):
    # Make test user admin
    from app.services.user_service import get_user_by_id

    user_id = authed_client.cookies.get("nekonoverse_session")
    # The test user is already set up via fixture; need to set admin role
    from sqlalchemy import update

    from app.models.user import User

    await db.execute(update(User).values(role="admin"))
    await db.flush()

    resp = await authed_client.get("/api/v1/admin/roles")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 3
    assert data[0]["name"] == "admin"


async def test_api_create_role(authed_client, db, seed_roles):
    from sqlalchemy import update

    from app.models.user import User

    await db.execute(update(User).values(role="admin"))
    await db.flush()

    resp = await authed_client.post(
        "/api/v1/admin/roles",
        json={"name": "editor", "display_name": "Editor"},
    )
    assert resp.status_code == 201
    assert resp.json()["name"] == "editor"


async def test_api_update_role(authed_client, db, seed_roles):
    from sqlalchemy import update

    from app.models.user import User

    await db.execute(update(User).values(role="admin"))
    await db.flush()

    resp = await authed_client.patch(
        "/api/v1/admin/roles/moderator",
        json={"display_name": "Mod Updated", "quota_bytes": 2147483648},
    )
    assert resp.status_code == 200
    assert resp.json()["display_name"] == "Mod Updated"
    assert resp.json()["quota_bytes"] == 2147483648


async def test_api_delete_system_role(authed_client, db, seed_roles):
    from sqlalchemy import update

    from app.models.user import User

    await db.execute(update(User).values(role="admin"))
    await db.flush()

    resp = await authed_client.delete("/api/v1/admin/roles/user")
    assert resp.status_code == 422


async def test_api_change_user_role_validates(authed_client, db, seed_roles):
    """Role change validates that role exists."""
    from sqlalchemy import update

    from app.models.user import User

    await db.execute(update(User).values(role="admin"))
    await db.flush()

    # Create another user to change
    from app.services.user_service import create_user

    target = await create_user(db, "target", "target@test.com", "pw123456", display_name="T")

    resp = await authed_client.patch(
        f"/api/v1/admin/users/{target.id}/role",
        json={"role": "nonexistent"},
    )
    assert resp.status_code == 422
    assert "does not exist" in resp.json()["detail"]
