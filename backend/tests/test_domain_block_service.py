"""Tests for domain_block_service: create, remove, list, is_blocked with Valkey cache."""

from unittest.mock import AsyncMock

from app.services.domain_block_service import (
    create_domain_block,
    is_domain_blocked,
    list_domain_blocks,
    remove_domain_block,
)

# -- create_domain_block --


async def test_create_domain_block(db, mock_valkey, test_user):
    block = await create_domain_block(db, "evil.example.com", "suspend", "spam server", test_user)

    assert block.domain == "evil.example.com"
    assert block.severity == "suspend"
    assert block.reason == "spam server"
    assert block.created_by_id == test_user.id


async def test_create_domain_block_duplicate(db, mock_valkey, test_user):
    await create_domain_block(db, "dup.example.com", "suspend", None, test_user)
    # 同じドメインに対する2回目の作成はIntegrityErrorになる
    import pytest
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        await create_domain_block(db, "dup.example.com", "silence", "again", test_user)


# -- remove_domain_block --


async def test_remove_domain_block(db, mock_valkey, test_user):
    await create_domain_block(db, "removeme.example.com", "suspend", None, test_user)
    result = await remove_domain_block(db, "removeme.example.com")
    assert result is True


async def test_remove_domain_block_not_found(db, mock_valkey):
    result = await remove_domain_block(db, "nonexistent.example.com")
    assert result is False


# -- list_domain_blocks --


async def test_list_domain_blocks_empty(db, mock_valkey):
    blocks = await list_domain_blocks(db)
    assert blocks == []


async def test_list_domain_blocks(db, mock_valkey, test_user):
    await create_domain_block(db, "block1.example.com", "suspend", None, test_user)
    await create_domain_block(db, "block2.example.com", "silence", "spam", test_user)

    blocks = await list_domain_blocks(db)
    assert len(blocks) >= 2
    domains = {b.domain for b in blocks}
    assert "block1.example.com" in domains
    assert "block2.example.com" in domains


# -- is_domain_blocked --


async def test_is_domain_blocked_true(db, mock_valkey, test_user):
    await create_domain_block(db, "bad.example.com", "suspend", None, test_user)
    # キャッシュミスの場合: getがNoneを返す(デフォルト)
    result = await is_domain_blocked(db, "bad.example.com")
    assert result is True


async def test_is_domain_blocked_false(db, mock_valkey):
    result = await is_domain_blocked(db, "safe.example.com")
    assert result is False


async def test_is_domain_blocked_cached_hit(db, mock_valkey):
    """Valkeyキャッシュにヒットした場合、DBクエリなしで結果を返す。"""
    mock_valkey.get = AsyncMock(return_value="1")
    result = await is_domain_blocked(db, "cached-blocked.example.com")
    assert result is True

    mock_valkey.get = AsyncMock(return_value="0")
    result = await is_domain_blocked(db, "cached-safe.example.com")
    assert result is False
