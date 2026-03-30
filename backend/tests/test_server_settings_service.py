"""Tests for server_settings_service: get, set, overwrite, get_all with Valkey cache."""

from app.services.server_settings_service import (
    get_all_settings,
    get_setting,
    set_setting,
)

# -- set_setting / get_setting --


async def test_set_and_get_setting(db, mock_valkey):
    await set_setting(db, "server_name", "Test Server")
    await db.commit()

    value = await get_setting(db, "server_name")
    assert value == "Test Server"


async def test_get_setting_not_found(db, mock_valkey):
    value = await get_setting(db, "nonexistent_key")
    assert value is None


async def test_set_setting_overwrite(db, mock_valkey):
    await set_setting(db, "site_title", "First Title")
    await db.commit()

    await set_setting(db, "site_title", "Second Title")
    await db.commit()

    value = await get_setting(db, "site_title")
    assert value == "Second Title"


async def test_set_setting_none_value(db, mock_valkey):
    await set_setting(db, "optional_key", "has value")
    await db.commit()

    await set_setting(db, "optional_key", None)
    await db.commit()

    value = await get_setting(db, "optional_key")
    assert value is None


# -- get_all_settings --


async def test_get_all_settings(db, mock_valkey):
    await set_setting(db, "key_a", "value_a")
    await set_setting(db, "key_b", "value_b")
    await set_setting(db, "key_c", None)
    await db.commit()

    all_settings = await get_all_settings(db)
    assert all_settings["key_a"] == "value_a"
    assert all_settings["key_b"] == "value_b"
    assert all_settings["key_c"] is None
