"""Extended tests for emoji_service covering remote emoji operations."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.custom_emoji import CustomEmoji
from app.services.emoji_service import (
    import_remote_emoji_to_local,
    list_remote_emoji_domains,
    list_remote_emojis,
    upsert_remote_emoji,
)


async def _create_remote_emoji(
    db,
    shortcode: str,
    domain: str,
    url: str = "https://remote.example/emoji.png",
    **kwargs,
) -> CustomEmoji:
    """Insert a remote CustomEmoji directly into the database."""
    emoji = CustomEmoji(
        shortcode=shortcode,
        domain=domain,
        url=url,
        visible_in_picker=False,
        **kwargs,
    )
    db.add(emoji)
    await db.flush()
    return emoji


# ── upsert_remote_emoji — update path ────────────────────────────────────


async def test_upsert_update_url_only(db):
    original = await _create_remote_emoji(
        db,
        "wave",
        "remote.example",
        url="https://remote.example/old.png",
        static_url="https://remote.example/old_static.png",
        author="original_author",
    )
    result = await upsert_remote_emoji(
        db,
        shortcode="wave",
        domain="remote.example",
        url="https://remote.example/new.png",
    )
    assert result.id == original.id
    assert result.url == "https://remote.example/new.png"
    assert result.static_url == "https://remote.example/old_static.png"
    assert result.author == "original_author"


async def test_upsert_update_all_optional_fields(db):
    original = await _create_remote_emoji(
        db,
        "sparkle",
        "remote.example",
        url="https://remote.example/sparkle_v1.png",
    )
    result = await upsert_remote_emoji(
        db,
        shortcode="sparkle",
        domain="remote.example",
        url="https://remote.example/sparkle_v2.png",
        static_url="https://remote.example/sparkle_v2_static.png",
        aliases=["glitter", "shine"],
        license="CC-BY-4.0",
        is_sensitive=True,
        author="artist_name",
        description="A sparkling emoji",
        copy_permission="allow",
        usage_info="Free to use",
        is_based_on="https://original.example/sparkle",
        category="effects",
    )
    assert result.id == original.id
    assert result.url == "https://remote.example/sparkle_v2.png"
    assert result.aliases == ["glitter", "shine"]
    assert result.license == "CC-BY-4.0"
    assert result.is_sensitive is True
    assert result.author == "artist_name"
    assert result.description == "A sparkling emoji"
    assert result.copy_permission == "allow"
    assert result.usage_info == "Free to use"
    assert result.is_based_on == "https://original.example/sparkle"
    assert result.category == "effects"


async def test_upsert_update_is_sensitive_to_false(db):
    original = await _create_remote_emoji(
        db,
        "flag",
        "remote.example",
        url="https://remote.example/flag.png",
        is_sensitive=True,
    )
    result = await upsert_remote_emoji(
        db,
        shortcode="flag",
        domain="remote.example",
        url="https://remote.example/flag.png",
        is_sensitive=False,
    )
    assert result.id == original.id
    assert result.is_sensitive is False


async def test_upsert_update_aliases_to_empty_list(db):
    await _create_remote_emoji(
        db,
        "cat",
        "remote.example",
        url="https://remote.example/cat.png",
        aliases=["neko", "kitty"],
    )
    result = await upsert_remote_emoji(
        db,
        shortcode="cat",
        domain="remote.example",
        url="https://remote.example/cat.png",
        aliases=[],
    )
    assert result.aliases == []


async def test_upsert_does_not_overwrite_with_none(db):
    await _create_remote_emoji(
        db,
        "heart",
        "remote.example",
        url="https://remote.example/heart.png",
        static_url="https://remote.example/heart_static.png",
        license="MIT",
        author="creator",
        description="A heart",
        copy_permission="allow",
        usage_info="Use freely",
        is_based_on="https://base.example",
        category="love",
    )
    # Noneのデフォルト値で呼び出す場合、既存の値が保持される
    result = await upsert_remote_emoji(
        db,
        shortcode="heart",
        domain="remote.example",
        url="https://remote.example/heart_v2.png",
    )
    assert result.url == "https://remote.example/heart_v2.png"
    assert result.static_url == "https://remote.example/heart_static.png"
    assert result.license == "MIT"
    assert result.author == "creator"


# ── list_remote_emojis ───────────────────────────────────────────────────


async def _seed_remote_emojis(db):
    await _create_remote_emoji(db, "smile", "alpha.example", url="https://a.example/smile.png")
    await _create_remote_emoji(db, "wave", "alpha.example", url="https://a.example/wave.png")
    await _create_remote_emoji(db, "smile", "beta.example", url="https://b.example/smile.png")
    await _create_remote_emoji(db, "fire", "beta.example", url="https://b.example/fire.png")
    await _create_remote_emoji(db, "smiling_cat", "gamma.example", url="https://g.example/sc.png")


async def test_list_all_remote_emojis(db):
    await _seed_remote_emojis(db)
    result = await list_remote_emojis(db)
    assert len(result) == 5


async def test_list_filter_by_domain(db):
    await _seed_remote_emojis(db)
    result = await list_remote_emojis(db, domain="alpha.example")
    assert len(result) == 2
    assert {e.shortcode for e in result} == {"smile", "wave"}


async def test_list_filter_by_search(db):
    await _seed_remote_emojis(db)
    result = await list_remote_emojis(db, search="smil")
    assert len(result) == 3


async def test_list_filter_domain_and_search(db):
    await _seed_remote_emojis(db)
    result = await list_remote_emojis(db, domain="beta.example", search="smil")
    assert len(result) == 1
    assert result[0].shortcode == "smile"


async def test_list_limit_and_offset(db):
    await _seed_remote_emojis(db)
    page1 = await list_remote_emojis(db, limit=2, offset=0)
    page2 = await list_remote_emojis(db, limit=2, offset=2)
    page3 = await list_remote_emojis(db, limit=2, offset=4)
    assert len(page1) == 2
    assert len(page2) == 2
    assert len(page3) == 1


# ── list_remote_emoji_domains ────────────────────────────────────────────


async def test_list_remote_emoji_domains_distinct(db):
    await _create_remote_emoji(db, "a", "zebra.example", url="https://z.example/a.png")
    await _create_remote_emoji(db, "b", "zebra.example", url="https://z.example/b.png")
    await _create_remote_emoji(db, "c", "alpha.example", url="https://a.example/c.png")
    result = await list_remote_emoji_domains(db)
    assert len(result) == 2
    assert result == ["alpha.example", "zebra.example"]


async def test_list_remote_emoji_domains_empty(db):
    result = await list_remote_emoji_domains(db)
    assert result == []


# ── import_remote_emoji_to_local ─────────────────────────────────────────


async def test_import_success(db):
    remote = await _create_remote_emoji(
        db,
        "imported",
        "source.example",
        url="https://source.example/imported.png",
        category="animals",
        aliases=["imp"],
        license="CC0",
        author="remote_artist",
        description="An imported emoji",
        copy_permission="allow",
        usage_info="Free use",
        is_based_on="https://base.example/original",
    )

    # DBにDriveFileレコードを作成してFK制約を満たす
    from app.models.drive_file import DriveFile

    drive_file = DriveFile(
        s3_key=f"emoji/imported_{uuid.uuid4().hex}.png",
        filename="imported.png",
        mime_type="image/png",
        size_bytes=1024,
    )
    db.add(drive_file)
    await db.flush()

    mock_response = MagicMock()
    mock_response.headers = {"content-type": "image/png"}
    mock_response.content = b"\x89PNG\r\n\x1a\nfakedata"
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.utils.network.is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_http_client),
        patch(
            "app.services.drive_service.upload_drive_file",
            new_callable=AsyncMock,
            return_value=drive_file,
        ),
        patch(
            "app.services.drive_service.file_to_url",
            return_value="https://local.example/emoji/imported.png",
        ),
    ):
        result = await import_remote_emoji_to_local(db, remote.id)

    assert result.shortcode == "imported"
    assert result.domain is None
    assert result.url == "https://local.example/emoji/imported.png"
    assert result.drive_file_id == drive_file.id
    assert result.category == "animals"


async def test_import_nonexistent_raises(db):
    with pytest.raises(ValueError, match="Remote emoji not found"):
        await import_remote_emoji_to_local(db, uuid.uuid4())


async def test_import_local_emoji_raises(db):
    local = CustomEmoji(
        shortcode="already_local",
        domain=None,
        url="https://local.example/already.png",
        visible_in_picker=True,
    )
    db.add(local)
    await db.flush()
    with pytest.raises(ValueError, match="Remote emoji not found"):
        await import_remote_emoji_to_local(db, local.id)


async def test_import_denied_by_copy_permission(db):
    remote = await _create_remote_emoji(
        db,
        "denied_emoji",
        "strict.example",
        url="https://strict.example/denied.png",
        copy_permission="deny",
    )
    with pytest.raises(ValueError, match="Import denied by author"):
        await import_remote_emoji_to_local(db, remote.id)


async def test_import_duplicate_local_shortcode_raises(db):
    remote = await _create_remote_emoji(
        db,
        "duplicate",
        "remote.example",
        url="https://remote.example/duplicate.png",
    )
    local = CustomEmoji(
        shortcode="duplicate",
        domain=None,
        url="https://local.example/duplicate.png",
        visible_in_picker=True,
    )
    db.add(local)
    await db.flush()
    with pytest.raises(ValueError, match="already exists"):
        await import_remote_emoji_to_local(db, remote.id)


async def test_import_unsupported_mime_type_raises(db):
    remote = await _create_remote_emoji(
        db,
        "svg_emoji",
        "remote.example",
        url="https://remote.example/emoji.svg",
    )

    mock_response = MagicMock()
    mock_response.headers = {"content-type": "image/svg+xml"}
    mock_response.content = b"<svg></svg>"
    mock_response.raise_for_status = MagicMock()

    mock_http_client = AsyncMock()
    mock_http_client.get = AsyncMock(return_value=mock_response)
    mock_http_client.__aenter__ = AsyncMock(return_value=mock_http_client)
    mock_http_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.utils.network.is_safe_url", return_value=True),
        patch("httpx.AsyncClient", return_value=mock_http_client),
    ):
        with pytest.raises(ValueError, match="Unsupported image type"):
            await import_remote_emoji_to_local(db, remote.id)
