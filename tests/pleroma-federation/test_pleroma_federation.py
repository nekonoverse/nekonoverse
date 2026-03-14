"""Pleroma cross-platform federation tests.

Tests Nekonoverse <-> Pleroma federation focusing on:
- ActivityPub endpoint compatibility
- Following flow (the known issue with followers/following collections)
- Note federation
"""

import httpx
import pytest

from conftest import (
    NEKO_DOMAIN,
    NEKO_URL,
    PLEROMA_DOMAIN,
    PLEROMA_URL,
    NekoClient,
    PleromaClient,
    poll_until,
)


class TestHealth:
    def test_nekonoverse_healthy(self, neko: NekoClient):
        assert neko.health() == {"status": "ok"}

    def test_pleroma_healthy(self, pleroma: PleromaClient):
        assert pleroma.health() is True


class TestRegistration:
    def test_alice_registered(self, alice):
        assert alice["username"] == "alice"

    def test_bob_registered(self, bob):
        # Pleroma registration returns access_token
        assert "access_token" in bob or "id" in bob

    def test_bob_credentials(self, pleroma: PleromaClient, bob):
        creds = pleroma.verify_credentials()
        assert creds["username"] == "bob"


class TestWebFinger:
    def test_neko_webfinger(self, neko: NekoClient, alice):
        result = neko.webfinger(f"alice@{NEKO_DOMAIN}")
        assert result["subject"] == f"acct:alice@{NEKO_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_pleroma_webfinger(self, pleroma: PleromaClient, bob):
        result = pleroma.webfinger(f"bob@{PLEROMA_DOMAIN}")
        assert result["subject"] == f"acct:bob@{PLEROMA_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_cross_instance_webfinger(self, alice, bob):
        """Both instances can resolve each other's WebFinger."""
        resp = httpx.get(
            f"{NEKO_URL}/.well-known/webfinger",
            params={"resource": f"acct:alice@{NEKO_DOMAIN}"},
            timeout=10,
            verify=False,
        )
        assert resp.status_code == 200

        resp = httpx.get(
            f"{PLEROMA_URL}/.well-known/webfinger",
            params={"resource": f"acct:bob@{PLEROMA_DOMAIN}"},
            timeout=10,
            verify=False,
        )
        assert resp.status_code == 200


class TestActorEndpoints:
    def test_neko_actor(self, neko: NekoClient, alice):
        actor = neko.get_actor_ap("alice")
        assert actor["type"] == "Person"
        assert actor["preferredUsername"] == "alice"
        assert "publicKey" in actor
        assert actor["publicKey"]["publicKeyPem"].startswith("-----BEGIN PUBLIC KEY-----")

    def test_neko_followers_collection_format(self, neko: NekoClient, alice):
        """Followers collection must have proper pagination (Pleroma compat)."""
        followers = neko.get_followers("alice")
        assert followers["type"] == "OrderedCollection"
        # first must NOT point back to the collection itself
        assert followers["first"] != followers["id"]
        assert "?page=true" in followers["first"]

    def test_neko_following_collection_format(self, neko: NekoClient, alice):
        """Following collection must have proper pagination (Pleroma compat)."""
        following = neko.get_following("alice")
        assert following["type"] == "OrderedCollection"
        assert following["first"] != following["id"]
        assert "?page=true" in following["first"]

    def test_neko_followers_page(self, neko: NekoClient, alice):
        """Followers page endpoint returns OrderedCollectionPage."""
        resp = httpx.get(
            f"{NEKO_URL}/users/alice/followers?page=true",
            headers={"Accept": "application/activity+json"},
            timeout=10,
            verify=False,
        )
        assert resp.status_code == 200
        page = resp.json()
        assert page["type"] == "OrderedCollectionPage"
        assert "partOf" in page
        assert "orderedItems" in page

    def test_neko_following_page(self, neko: NekoClient, alice):
        """Following page endpoint returns OrderedCollectionPage."""
        resp = httpx.get(
            f"{NEKO_URL}/users/alice/following?page=true",
            headers={"Accept": "application/activity+json"},
            timeout=10,
            verify=False,
        )
        assert resp.status_code == 200
        page = resp.json()
        assert page["type"] == "OrderedCollectionPage"
        assert "partOf" in page
        assert "orderedItems" in page


class TestNotes:
    def test_alice_creates_note(self, neko: NekoClient, alice):
        note = neko.create_note("Hello from Nekonoverse! Testing Pleroma federation.")
        assert note["content"] is not None
        assert note["actor"]["username"] == "alice"

    def test_bob_creates_status(self, pleroma: PleromaClient, bob):
        status = pleroma.create_status("Hello from Pleroma! Testing federation.")
        assert status["content"] is not None


class TestFederation:
    """Test cross-platform federation flow."""

    def test_01_bob_resolves_alice(self, pleroma: PleromaClient, alice, bob):
        """Bob on Pleroma can resolve alice@nekonoverse."""
        accounts = pleroma.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        assert len(accounts) > 0
        alice_on_pleroma = accounts[0]
        assert alice_on_pleroma["username"] == "alice"
        # Store for later tests
        self.__class__.alice_id_on_pleroma = alice_on_pleroma["id"]

    def test_02_bob_follows_alice(self, pleroma: PleromaClient, bob):
        """Bob on Pleroma follows alice on Nekonoverse.

        This is the core test — the Pleroma error 'WithClauseError' on
        collection_private/1 was caused by Nekonoverse returning followers/following
        collections with 'first' pointing back to the collection URL instead of a
        page URL.
        """
        result = pleroma.follow(self.__class__.alice_id_on_pleroma)
        # Pleroma returns the relationship
        assert result is not None

    def test_03_alice_receives_follow(self, neko: NekoClient, alice, bob):
        """Alice on Nekonoverse receives and accepts the follow from bob."""
        def check_follower():
            followers = neko.get_followers("alice")
            return followers["totalItems"] > 0

        poll_until(check_follower, timeout=30, interval=2, desc="alice has followers")

    def test_04_alice_note_federates_to_pleroma(
        self, neko: NekoClient, pleroma: PleromaClient, alice, bob
    ):
        """Note created by alice on Nekonoverse appears in bob's timeline on Pleroma."""
        neko.create_note("Federation test note from alice to bob!")

        def check_note():
            # Check bob's home timeline for alice's note
            resp = pleroma.http.get(
                "/api/v1/timelines/home",
                params={"limit": "20"},
                headers=pleroma._headers(),
            )
            if resp.status_code != 200:
                return False
            tl = resp.json()
            return any("Federation test note" in s.get("content", "") for s in tl)

        poll_until(check_note, timeout=30, interval=2, desc="alice's note on bob's timeline")
