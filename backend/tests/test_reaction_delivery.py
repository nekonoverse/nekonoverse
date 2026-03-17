"""Tests for reaction delivery: software-based Like vs EmojiReact routing."""

from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.utils.nodeinfo import supports_emoji_reactions, uses_emoji_react


class TestUsesEmojiReact:
    """Verify software detection routes EmojiReact correctly."""

    @pytest.mark.parametrize("software", ["pleroma", "akkoma", "fedibird", "nekonoverse"])
    async def test_emoji_react_software(self, software):
        with patch(
            "app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, return_value=software
        ):
            assert await uses_emoji_react("example.com") is True

    @pytest.mark.parametrize("software", ["misskey", "mastodon", "gotosocial", "hubzilla"])
    async def test_like_software(self, software):
        with patch(
            "app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, return_value=software
        ):
            assert await uses_emoji_react("example.com") is False

    async def test_unknown_software_defaults_to_like(self):
        with patch(
            "app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, return_value=None
        ):
            assert await uses_emoji_react("example.com") is False


class TestSupportsEmojiReactions:
    """Verify supports_emoji_reactions covers EmojiReact + Misskey-compat software."""

    @pytest.mark.parametrize(
        "software",
        ["pleroma", "akkoma", "fedibird", "nekonoverse", "misskey", "calckey", "firefish", "sharkey"],
    )
    async def test_reaction_capable_software(self, software):
        with patch(
            "app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, return_value=software
        ):
            assert await supports_emoji_reactions("example.com") is True

    @pytest.mark.parametrize("software", ["mastodon", "gotosocial", "hubzilla"])
    async def test_reaction_incapable_software(self, software):
        with patch(
            "app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, return_value=software
        ):
            assert await supports_emoji_reactions("example.com") is False

    async def test_unknown_software_not_supported(self):
        with patch(
            "app.utils.nodeinfo.get_domain_software", new_callable=AsyncMock, return_value=None
        ):
            assert await supports_emoji_reactions("example.com") is False


class TestGetDomainSoftware:
    """Verify nodeinfo fetching and caching."""

    async def test_fetches_and_caches(self):
        from app.utils.nodeinfo import get_domain_software

        nodeinfo_discovery = {
            "links": [
                {
                    "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                    "href": "https://example.com/nodeinfo/2.0",
                }
            ]
        }
        nodeinfo_response = {"software": {"name": "Pleroma", "version": "2.5.5"}}

        mock_valkey = AsyncMock()
        mock_valkey.get = AsyncMock(return_value=None)  # Cache miss
        mock_valkey.set = AsyncMock()

        import httpx

        responses = [
            httpx.Response(200, json=nodeinfo_discovery),
            httpx.Response(200, json=nodeinfo_response),
        ]

        with (
            patch("app.valkey_client.valkey", mock_valkey),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=responses)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_domain_software("example.com")

        assert result == "pleroma"
        mock_valkey.set.assert_any_call(
            "nodeinfo:software:example.com", "pleroma", ex=86400
        )
        mock_valkey.set.assert_any_call(
            "nodeinfo:software_version:example.com", "2.5.5", ex=86400
        )

    async def test_returns_cached_value(self):
        from app.utils.nodeinfo import get_domain_software

        mock_valkey = AsyncMock()
        mock_valkey.get = AsyncMock(return_value=b"akkoma")

        with patch("app.valkey_client.valkey", mock_valkey):
            result = await get_domain_software("example.com")

        assert result == "akkoma"

    async def test_cached_empty_returns_none(self):
        from app.utils.nodeinfo import get_domain_software

        mock_valkey = AsyncMock()
        mock_valkey.get = AsyncMock(return_value=b"")

        with patch("app.valkey_client.valkey", mock_valkey):
            result = await get_domain_software("example.com")

        assert result is None

    async def test_fetch_failure_returns_none(self):
        from app.utils.nodeinfo import get_domain_software

        mock_valkey = AsyncMock()
        mock_valkey.get = AsyncMock(return_value=None)
        mock_valkey.set = AsyncMock()

        with (
            patch("app.valkey_client.valkey", mock_valkey),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=httpx.ConnectError("timeout"))
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await get_domain_software("unreachable.example")

        assert result is None
        # Should cache the failure as empty string
        mock_valkey.set.assert_any_call(
            "nodeinfo:software:unreachable.example", "", ex=86400
        )
        mock_valkey.set.assert_any_call(
            "nodeinfo:software_version:unreachable.example", "", ex=86400
        )


class TestGetDomainSoftwareInfo:
    async def test_returns_name_and_version(self):
        from app.utils.nodeinfo import get_domain_software_info

        nodeinfo_discovery = {
            "links": [
                {
                    "rel": "http://nodeinfo.diaspora.software/ns/schema/2.0",
                    "href": "https://example.com/nodeinfo/2.0",
                }
            ]
        }
        nodeinfo_response = {"software": {"name": "Misskey", "version": "2026.3.1"}}

        mock_valkey = AsyncMock()
        mock_valkey.get = AsyncMock(return_value=None)
        mock_valkey.set = AsyncMock()

        responses = [
            httpx.Response(200, json=nodeinfo_discovery),
            httpx.Response(200, json=nodeinfo_response),
        ]

        with (
            patch("app.valkey_client.valkey", mock_valkey),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=responses)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            name, version = await get_domain_software_info("example.com")

        assert name == "misskey"
        assert version == "2026.3.1"

    async def test_returns_cached_name_and_version(self):
        from app.utils.nodeinfo import get_domain_software_info

        mock_valkey = AsyncMock()
        mock_valkey.get = AsyncMock(side_effect=[b"sharkey", b"4.0.0"])

        with patch("app.valkey_client.valkey", mock_valkey):
            name, version = await get_domain_software_info("example.com")

        assert name == "sharkey"
        assert version == "4.0.0"

    async def test_cached_empty_returns_none_tuple(self):
        from app.utils.nodeinfo import get_domain_software_info

        mock_valkey = AsyncMock()
        mock_valkey.get = AsyncMock(side_effect=[b"", b""])

        with patch("app.valkey_client.valkey", mock_valkey):
            name, version = await get_domain_software_info("example.com")

        assert name is None
        assert version is None
