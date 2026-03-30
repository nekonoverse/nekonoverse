"""Tests for role_service."""

from app.services.role_service import (
    create_role,
    delete_role,
    get_all_roles,
    get_quota_for_user,
    get_role,
    has_permission,
    role_exists,
    update_role,
)


async def test_create_role(db):
    """Creating a custom role stores it correctly."""
    role = await create_role(db, "vip", "VIP User")
    assert role.name == "vip"
    assert role.display_name == "VIP User"
    assert role.is_system is False
    assert role.quota_bytes == 1073741824  # 1 GB default
    assert role.permissions == {}


async def test_create_role_copy_from(db, seed_roles):
    """Creating a role with copy_from copies permissions and quota from the source."""
    role = await create_role(db, "senior_mod", "Senior Moderator", copy_from="moderator")
    assert role.permissions.get("users") is True
    assert role.permissions.get("reports") is True
    assert role.quota_bytes == 5368709120


async def test_get_role_exists(db, seed_roles):
    """Getting an existing role returns it."""
    role = await get_role(db, "moderator")
    assert role is not None
    assert role.display_name == "Moderator"
    assert role.quota_bytes == 5368709120


async def test_get_role_not_found(db):
    """Getting a non-existent role returns None."""
    role = await get_role(db, "nonexistent")
    assert role is None


async def test_get_all_roles(db, seed_roles):
    """Getting all roles returns them sorted by priority descending."""
    roles = await get_all_roles(db)
    assert len(roles) == 3
    assert roles[0].name == "admin"
    assert roles[1].name == "moderator"
    assert roles[2].name == "user"


async def test_update_role(db, seed_roles):
    """Updating a role changes the specified fields."""
    role = await update_role(db, "moderator", display_name="Mod", quota_bytes=10737418240)
    assert role.display_name == "Mod"
    assert role.quota_bytes == 10737418240


async def test_delete_role(db):
    """Deleting a non-system role removes it."""
    await create_role(db, "temp", "Temporary")
    await delete_role(db, "temp")
    assert await get_role(db, "temp") is None


async def test_has_permission_admin_always_true(db, seed_roles):
    """Admin role always has any permission."""
    from app.services.user_service import create_user

    admin_user = await create_user(
        db, "adminuser", "admin@example.com", "password1234", role="admin"
    )
    assert await has_permission(db, admin_user, "users") is True
    assert await has_permission(db, admin_user, "anything") is True
    assert await has_permission(db, admin_user, "nonexistent_perm") is True


async def test_has_permission_moderator(db, seed_roles):
    """Moderator role has 'users' permission but not arbitrary ones."""
    from app.services.user_service import create_user

    mod_user = await create_user(
        db, "moduser", "mod@example.com", "password1234", role="moderator"
    )
    assert await has_permission(db, mod_user, "users") is True
    assert await has_permission(db, mod_user, "reports") is True
    assert await has_permission(db, mod_user, "nonexistent_perm") is False


async def test_has_permission_user_false(db, seed_roles):
    """Normal user has no moderation permissions."""
    from app.services.user_service import create_user

    normal_user = await create_user(
        db, "normaluser", "normal@example.com", "password1234", role="user"
    )
    assert await has_permission(db, normal_user, "users") is False
    assert await has_permission(db, normal_user, "reports") is False


async def test_get_quota_for_user(db, seed_roles):
    """Normal user returns the user role's quota_bytes."""
    from app.services.user_service import create_user

    normal_user = await create_user(
        db, "quotauser", "quota@example.com", "password1234", role="user"
    )
    quota = await get_quota_for_user(db, normal_user)
    assert quota == 1073741824  # 1 GB


async def test_role_exists_true(db, seed_roles):
    """role_exists returns True for an existing role."""
    assert await role_exists(db, "admin") is True
    assert await role_exists(db, "user") is True


async def test_role_exists_false(db):
    """role_exists returns False for a non-existent role."""
    assert await role_exists(db, "nonexistent") is False
