"""Mitra cross-platform federation tests.

Tests Nekonoverse <-> Mitra federation focusing on:
- ActivityPub endpoint compatibility
- Following flow (known issue with Mitra follow relationships)
- Unfollow propagation
- Note federation
- Reaction/favourite federation
"""

import time

import httpx
import pytest

from conftest import (
    NEKO_DOMAIN,
    NEKO_URL,
    MITRA_DOMAIN,
    MITRA_URL,
    NekoClient,
    MitraClient,
    poll_until,
)


class TestHealth:
    def test_nekonoverse_healthy(self, neko: NekoClient):
        assert neko.health() == {"status": "ok"}

    def test_mitra_healthy(self, mitra: MitraClient):
        assert mitra.health() is True


class TestRegistration:
    def test_alice_registered(self, alice):
        assert alice["username"] == "alice"

    def test_bob_registered(self, bob):
        # Mitra login returns access_token
        assert "access_token" in bob

    def test_bob_credentials(self, mitra: MitraClient, bob):
        creds = mitra.verify_credentials()
        assert creds["username"] == "bob"


class TestWebFinger:
    def test_neko_webfinger(self, neko: NekoClient, alice):
        result = neko.webfinger(f"alice@{NEKO_DOMAIN}")
        assert result["subject"] == f"acct:alice@{NEKO_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_mitra_webfinger(self, mitra: MitraClient, bob):
        result = mitra.webfinger(f"bob@{MITRA_DOMAIN}")
        assert result["subject"] == f"acct:bob@{MITRA_DOMAIN}"
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
            f"{MITRA_URL}/.well-known/webfinger",
            params={"resource": f"acct:bob@{MITRA_DOMAIN}"},
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
        """Followers collection must have proper pagination (Mitra compat)."""
        followers = neko.get_followers("alice")
        assert followers["type"] == "OrderedCollection"
        # first must NOT point back to the collection itself
        assert followers["first"] != followers["id"]
        assert "?page=true" in followers["first"]

    def test_neko_following_collection_format(self, neko: NekoClient, alice):
        """Following collection must have proper pagination (Mitra compat)."""
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
        note = neko.create_note("Hello from Nekonoverse! Testing Mitra federation.")
        assert note["content"] is not None
        assert note["actor"]["username"] == "alice"

    def test_bob_creates_status(self, mitra: MitraClient, bob):
        status = mitra.create_status("Hello from Mitra! Testing federation.")
        assert status["content"] is not None


class TestFederation:
    """Test cross-platform federation flow with emphasis on follow relationships."""

    def test_01_bob_resolves_alice(self, mitra: MitraClient, alice, bob):
        """Bob on Mitra can resolve alice@nekonoverse."""
        accounts = mitra.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        assert len(accounts) > 0
        alice_on_mitra = accounts[0]
        assert alice_on_mitra["username"] == "alice"
        self.__class__.alice_id_on_mitra = alice_on_mitra["id"]

    def test_02_bob_follows_alice(self, mitra: MitraClient, bob):
        """Bob on Mitra follows alice on Nekonoverse."""
        result = mitra.follow(self.__class__.alice_id_on_mitra)
        assert result is not None

    def test_03_alice_receives_follow(self, neko: NekoClient, alice, bob):
        """Alice on Nekonoverse receives and accepts the follow from bob."""
        def check_follower():
            followers = neko.get_followers("alice")
            return followers["totalItems"] > 0

        poll_until(check_follower, timeout=30, interval=2, desc="alice has followers")

    def test_04_alice_note_federates_to_mitra(
        self, neko: NekoClient, mitra: MitraClient, alice, bob
    ):
        """Note created by alice on Nekonoverse appears in bob's timeline on Mitra."""
        unique = f"Fed test neko to mitra {time.time()}"
        neko.create_note(unique)

        def check_note():
            tl = mitra.timeline_home()
            return any(unique in s.get("content", "") for s in tl)

        poll_until(check_note, timeout=30, interval=2, desc="alice's note on bob's timeline")

    def test_05_alice_resolves_bob(self, neko: NekoClient, alice, bob):
        """Alice on Nekonoverse can resolve bob@mitra."""
        accounts = neko.search_accounts(f"bob@{MITRA_DOMAIN}", resolve=True)
        assert len(accounts) > 0
        bob_on_neko = accounts[0]
        assert bob_on_neko["username"] == "bob"
        self.__class__.bob_id_on_neko = bob_on_neko["id"]

    def test_06_alice_follows_bob(self, neko: NekoClient, alice):
        """Alice on Nekonoverse follows bob on Mitra (reverse direction)."""
        result = neko.follow(self.__class__.bob_id_on_neko)
        assert result is not None

    def test_07_bob_receives_follow(self, mitra: MitraClient, alice, bob):
        """Bob on Mitra receives the follow notification from alice."""
        def check_notification():
            notifs = mitra.get_notifications()
            return any(
                n.get("type") == "follow"
                and n.get("account", {}).get("username") == "alice"
                for n in notifs
            )

        poll_until(check_notification, timeout=30, interval=2, desc="bob receives follow")

    def test_08_bob_note_federates_to_neko(
        self, neko: NekoClient, mitra: MitraClient, alice, bob
    ):
        """Note created by bob on Mitra appears in alice's timeline on Nekonoverse."""
        unique = f"Fed test mitra to neko {time.time()}"
        mitra.create_status(unique)

        def check_note():
            tl = neko.home_timeline()
            return any(unique in s.get("content", "") for s in tl)

        poll_until(check_note, timeout=60, interval=2, desc="bob's note on alice's timeline")

    def test_09_mutual_follow_state(self, mitra: MitraClient, bob):
        """Verify mutual follow state on Mitra side."""
        rels = mitra.get_relationships([self.__class__.alice_id_on_mitra])
        assert len(rels) > 0
        rel = rels[0]
        assert rel["following"] is True, f"bob should be following alice: {rel}"
        assert rel["followed_by"] is True, f"alice should be following bob: {rel}"

    def test_10_unfollow_bob_to_alice(self, mitra: MitraClient, bob):
        """Bob on Mitra unfollows alice on Nekonoverse."""
        result = mitra.unfollow(self.__class__.alice_id_on_mitra)
        assert result is not None

    def test_11_unfollow_propagated(self, neko: NekoClient, alice, bob):
        """Unfollow is propagated to Nekonoverse — alice's follower count decreases."""
        def check_no_follower():
            followers = neko.get_followers("alice")
            return followers["totalItems"] == 0

        poll_until(
            check_no_follower, timeout=30, interval=2, desc="unfollow propagated to neko"
        )


# ── Reaction federation ─────────────────────────────────────────


class TestReactionFederation:
    """Test that Neko sends EmojiReact / Like to Mitra and it arrives."""

    @pytest.mark.xfail(reason="Mitra processes EmojiReact but does not expose it as favourite notification")
    def test_neko_reaction_arrives_on_mitra(
        self, neko: NekoClient, mitra: MitraClient, alice, bob
    ):
        """alice@neko reacts to bob@mitra's status; Mitra receives a favourite."""
        # bob creates a status on Mitra
        unique = f"React to me Mitra {time.time()}"
        mitra_status = mitra.create_status(unique)

        # Wait for it to federate to Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(
            find_on_neko, timeout=60, interval=2, desc="mitra note on neko"
        )

        # alice reacts with 👍
        neko.react(neko_note["id"], "👍")

        # Check on Mitra — should appear as a favourite notification
        def check_favourite_on_mitra():
            notifs = mitra.get_notifications()
            return any(
                n.get("type") == "favourite"
                and n.get("account", {}).get("username") == "alice"
                for n in notifs
            )

        poll_until(
            check_favourite_on_mitra, timeout=60, interval=2,
            desc="reaction/favourite notification on mitra",
        )

        # Also verify the status shows as favourited
        status = mitra.get_status(mitra_status["id"])
        assert status.get("favourites_count", 0) >= 1, (
            f"Expected favourites_count >= 1, got {status.get('favourites_count')}"
        )
