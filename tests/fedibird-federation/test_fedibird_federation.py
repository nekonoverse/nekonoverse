"""Fedibird cross-platform federation tests.

Tests Nekonoverse <-> Fedibird federation covering:
- Health checks, WebFinger, Actor endpoints
- Note creation and federation
- Follow flow
- Reply federation
- Mention / notification federation
- Delete federation
- Boost (reblog/announce) federation
- Favourite (like) federation
- Emoji reaction federation (Fedibird extension)
- CW (spoiler_text / sensitive) federation
- Hashtag federation
"""

import time

import httpx
import pytest

from conftest import (
    FEDIBIRD_DOMAIN,
    FEDIBIRD_URL,
    NEKO_DOMAIN,
    NEKO_URL,
    FedibirdClient,
    NekoClient,
    poll_until,
)


def _get(url: str, **kwargs):
    kwargs.setdefault("verify", False)
    kwargs.setdefault("timeout", 15)
    return httpx.get(url, **kwargs)


# ── 1. Health checks ──────────────────────────────────────────


class TestHealth:
    def test_nekonoverse_healthy(self, neko: NekoClient):
        assert neko.health() == {"status": "ok"}

    def test_fedibird_healthy(self, fedibird: FedibirdClient):
        assert fedibird.health() is True


# ── 2. Registration ───────────────────────────────────────────


class TestRegistration:
    def test_alice_registered(self, alice):
        assert alice["username"] == "alice"

    def test_bob_registered(self, bob):
        assert "access_token" in bob or "id" in bob

    def test_bob_credentials(self, fedibird: FedibirdClient, bob):
        creds = fedibird.verify_credentials()
        assert creds["username"] == "bob"


# ── 3. WebFinger ──────────────────────────────────────────────


class TestWebFinger:
    def test_neko_webfinger(self, neko: NekoClient, alice):
        result = neko.webfinger(f"alice@{NEKO_DOMAIN}")
        assert result["subject"] == f"acct:alice@{NEKO_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_fedibird_webfinger(self, fedibird: FedibirdClient, bob):
        result = fedibird.webfinger(f"bob@{FEDIBIRD_DOMAIN}")
        assert result["subject"] == f"acct:bob@{FEDIBIRD_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_cross_webfinger_neko_from_fedibird(self, alice, bob):
        """Fedibird can resolve Neko's WebFinger."""
        resp = _get(
            f"{NEKO_URL}/.well-known/webfinger",
            params={"resource": f"acct:alice@{NEKO_DOMAIN}"},
        )
        assert resp.status_code == 200

    def test_cross_webfinger_fedibird_from_neko(self, alice, bob):
        """Neko can resolve Fedibird's WebFinger."""
        resp = _get(
            f"{FEDIBIRD_URL}/.well-known/webfinger",
            params={"resource": f"acct:bob@{FEDIBIRD_DOMAIN}"},
        )
        assert resp.status_code == 200


# ── 4. Actor endpoints ───────────────────────────────────────


class TestActor:
    def test_neko_actor(self, neko: NekoClient, alice):
        actor = neko.get_actor_ap("alice")
        assert actor["type"] == "Person"
        assert actor["preferredUsername"] == "alice"
        assert "publicKey" in actor
        assert actor["publicKey"]["publicKeyPem"].startswith("-----BEGIN PUBLIC KEY-----")

    def test_fedibird_actor(self, fedibird: FedibirdClient, bob):
        """Fedibird actor endpoint returns valid AP Person."""
        wf = fedibird.webfinger(f"bob@{FEDIBIRD_DOMAIN}")
        actor_url = None
        for link in wf["links"]:
            if link.get("rel") == "self":
                actor_url = link["href"]
                break
        assert actor_url is not None
        actor = fedibird.get_actor_ap(actor_url)
        assert actor["type"] == "Person"
        assert actor["preferredUsername"] == "bob"
        assert "publicKey" in actor

    def test_neko_actor_has_endpoints(self, neko: NekoClient, alice):
        actor = neko.get_actor_ap("alice")
        assert "inbox" in actor
        assert "outbox" in actor
        assert "followers" in actor
        assert "following" in actor


# ── 5. Notes ──────────────────────────────────────────────────


class TestNotes:
    def test_neko_create_note(self, neko: NekoClient, alice):
        note = neko.create_note("Hello from Nekonoverse for Fedibird test!")
        assert note["content"] is not None
        assert note["actor"]["username"] == "alice"

    def test_fedibird_create_status(self, fedibird: FedibirdClient, bob):
        status = fedibird.create_status("Hello from Fedibird for federation test!")
        assert status["content"] is not None

    def test_neko_note_ap_format(self, neko: NekoClient, alice):
        """Neko note AP representation is Fedibird-compatible."""
        note = neko.create_note(f"AP format check {time.time()}")
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
        )
        assert resp.status_code == 200
        ap = resp.json()
        assert ap["type"] == "Note"
        assert "attributedTo" in ap
        assert "to" in ap
        assert "content" in ap


# ── 6. NodeInfo ───────────────────────────────────────────────


class TestNodeInfo:
    def test_neko_nodeinfo(self, alice):
        resp = _get(f"{NEKO_URL}/.well-known/nodeinfo")
        assert resp.status_code == 200
        data = resp.json()
        assert "links" in data
        link_url = data["links"][0]["href"]
        resp2 = _get(link_url)
        assert resp2.status_code == 200
        ni = resp2.json()
        assert ni["software"]["name"] == "nekonoverse"

    def test_fedibird_nodeinfo(self, bob):
        resp = _get(f"{FEDIBIRD_URL}/.well-known/nodeinfo")
        assert resp.status_code == 200
        data = resp.json()
        assert "links" in data
        link_url = data["links"][0]["href"]
        resp2 = _get(link_url)
        assert resp2.status_code == 200
        ni = resp2.json()
        # Fedibird identifies as "mastodon" or "fedibird" in nodeinfo
        assert ni["software"]["name"] in ("mastodon", "fedibird")


# ── 7. Follow federation ─────────────────────────────────────


class TestFollowFederation:
    """Test follow flow between Fedibird and Nekonoverse."""

    def test_fedibird_resolves_neko_user(self, fedibird: FedibirdClient, alice, bob):
        """Bob on Fedibird resolves alice@nekonoverse."""
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        assert len(accounts) > 0
        assert accounts[0]["username"] == "alice"

    def test_fedibird_follows_neko_user(self, fedibird: FedibirdClient, alice, bob):
        """Bob on Fedibird follows alice@nekonoverse."""
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        assert len(accounts) > 0
        result = fedibird.follow(accounts[0]["id"])
        assert result is not None

    def test_neko_receives_follower(self, neko: NekoClient, alice, bob):
        """Alice has bob@fedibird as a follower."""
        def check_followers():
            resp = neko.http.get(
                "/users/alice/followers",
                headers={"Accept": "application/activity+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("totalItems", 0) > 0
            return False

        poll_until(check_followers, desc="alice has followers")

    def test_neko_note_federates_to_fedibird(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """Note by alice on Neko appears on Fedibird's public timeline."""
        unique = f"Fed note to Fedibird {time.time()}"
        neko.create_note(unique)

        def check():
            tl = fedibird.timeline_public()
            return any(unique in (s.get("content") or "") for s in tl)

        poll_until(check, desc="neko note on fedibird")


# ── 8. Reply federation ──────────────────────────────────────


class TestReplyFederation:
    """Test reply federation between Fedibird and Nekonoverse."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, fedibird: FedibirdClient):
        if cls._follow_established:
            return
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                fedibird.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_fedibird(self, neko: NekoClient, fedibird: FedibirdClient, text: str):
        """Create a note on Neko and wait for it to appear on Fedibird."""
        self._ensure_follow(neko, fedibird)
        note = neko.create_note(text)

        def find_note():
            tl = fedibird.timeline_public()
            for s in tl:
                if text in (s.get("content") or ""):
                    return s
            return None

        fb_status = poll_until(find_note, desc=f"'{text}' on fedibird")
        return note, fb_status

    def test_fedibird_reply_to_neko_note(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob@fedibird replies to alice@neko's note; reply federates back."""
        note, fb_status = self._wait_for_note_on_fedibird(
            neko, fedibird, f"Reply target FB {time.time()}"
        )
        fedibird.create_status(
            f"Reply from Fedibird {time.time()}", in_reply_to_id=fb_status["id"]
        )

        def check_reply():
            ctx = neko.get_context(note["id"])
            return len(ctx.get("descendants", [])) >= 1

        poll_until(check_reply, timeout=120, desc="reply federated to neko")

    def test_neko_reply_to_fedibird_note(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """alice@neko replies to bob@fedibird's note."""
        # alice follows bob so notes federate
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Reply me from Neko FB {time.time()}"
        fb_status = fedibird.create_status(unique)

        # Wait for note to appear on Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="fedibird note on neko")

        # alice replies
        reply_text = f"Neko reply FB {time.time()}"
        neko.create_note(reply_text, in_reply_to_id=neko_note["id"])

        # Check reply on Fedibird
        def check_reply_on_fedibird():
            ctx = fedibird.get_context(fb_status["id"])
            return any(reply_text in (r.get("content") or "") for r in ctx.get("descendants", []))

        poll_until(check_reply_on_fedibird, timeout=120, desc="neko reply on fedibird")

    def test_reply_thread_context(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """Reply chain creates a proper thread context on Neko."""
        note, fb_status = self._wait_for_note_on_fedibird(
            neko, fedibird, f"Thread ctx FB {time.time()}"
        )
        fedibird.create_status(
            f"Reply in thread FB {time.time()}", in_reply_to_id=fb_status["id"]
        )

        def check_context():
            ctx = neko.get_context(note["id"])
            return len(ctx.get("descendants", [])) >= 1

        poll_until(check_context, desc="reply in thread context")

        ctx = neko.get_context(note["id"])
        assert len(ctx["descendants"]) >= 1
        descendant = ctx["descendants"][0]
        assert descendant["in_reply_to_id"] == note["id"]


# ── 9. Mention federation ────────────────────────────────────


class TestMentionFederation:
    """Test that @mentions federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, fedibird: FedibirdClient):
        if cls._follow_established:
            return
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                fedibird.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_mentions_fedibird_user(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """alice@neko creates a note mentioning @bob@fedibird."""
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0

        unique = f"Hey @bob@{FEDIBIRD_DOMAIN} check this {time.time()}"
        note = neko.create_note(unique)
        assert "id" in note

        # Verify the AP representation has mention tags
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
        )
        assert resp.status_code == 200
        ap_note = resp.json()
        tags = ap_note.get("tag", [])
        mention_tags = [t for t in tags if t.get("type") == "Mention"]
        assert len(mention_tags) >= 1, f"No Mention tags found in {tags}"

    def test_fedibird_mentions_neko_user(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob@fedibird mentions @alice@nekonoverse; alice should get a notification."""
        self._ensure_follow(neko, fedibird)

        unique = f"Hey @alice@{NEKO_DOMAIN} look {time.time()}"
        fedibird.create_status(unique)

        def check_mention_notification():
            notifs = neko.notifications(limit=30)
            return any(n.get("type") == "mention" for n in notifs)

        poll_until(check_mention_notification, desc="mention notification on neko")


# ── 10. Delete federation ────────────────────────────────────


class TestDeleteFederation:
    """Test that note deletions federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, fedibird: FedibirdClient):
        if cls._follow_established:
            return
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                fedibird.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_deletes_note_federates_to_fedibird(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """alice deletes a note; it should disappear from Fedibird."""
        self._ensure_follow(neko, fedibird)
        unique = f"Delete me FB {time.time()}"
        note = neko.create_note(unique)

        # Wait for note on Fedibird
        def find_note():
            tl = fedibird.timeline_public()
            for s in tl:
                if unique in (s.get("content") or ""):
                    return s
            return None

        fb_status = poll_until(find_note, desc="note on fedibird")

        # Delete on Neko
        neko.delete_note(note["id"])

        # Wait for deletion to federate
        def check_deleted():
            try:
                fedibird.get_status(fb_status["id"])
                return False  # Still exists
            except Exception:
                return True  # Deleted (404)

        poll_until(check_deleted, desc="deletion federated to fedibird")

    def test_fedibird_deletes_note_federates_to_neko(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob deletes a note; it should disappear from Neko."""
        # alice follows bob so notes federate
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"FB delete me {time.time()}"
        fb_status = fedibird.create_status(unique)

        # Wait for note on Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="fedibird note on neko")

        # Delete on Fedibird
        fedibird.delete_status(fb_status["id"])

        # Wait for deletion to federate
        def check_deleted():
            try:
                neko.get_note(neko_note["id"])
                return False
            except Exception:
                return True

        poll_until(check_deleted, desc="fedibird deletion federated to neko")


# ── 11. Boost (Announce) federation ──────────────────────────


class TestBoostFederation:
    """Test that boosts/reblogs federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, fedibird: FedibirdClient):
        if cls._follow_established:
            return
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                fedibird.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_fedibird(self, neko, fedibird, text):
        self._ensure_follow(neko, fedibird)
        note = neko.create_note(text)

        def find_note():
            tl = fedibird.timeline_public()
            for s in tl:
                if text in (s.get("content") or ""):
                    return s
            return None

        fb_status = poll_until(find_note, desc=f"'{text}' on fedibird")
        return note, fb_status

    def test_fedibird_boosts_neko_note(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob@fedibird boosts alice@neko's note; renotes_count increases."""
        note, fb_status = self._wait_for_note_on_fedibird(
            neko, fedibird, f"Boost me FB {time.time()}"
        )
        fedibird.reblog(fb_status["id"])

        def check_count():
            n = neko.get_note(note["id"])
            return n.get("renotes_count", 0) >= 1

        poll_until(check_count, desc="renotes_count >= 1")

    def test_fedibird_boost_creates_notification_on_neko(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """Boost from Fedibird creates a notification for the original author."""
        note, fb_status = self._wait_for_note_on_fedibird(
            neko, fedibird, f"Boost notif FB {time.time()}"
        )
        fedibird.reblog(fb_status["id"])

        def check_notification():
            notifs = neko.notifications(limit=20)
            return any(
                n.get("type") in ("renote", "reblog")
                and n.get("status", {}).get("id") == note["id"]
                for n in notifs
            )

        poll_until(check_notification, timeout=120, desc="boost notification on neko")

    def test_neko_boost_federates_to_fedibird(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """alice@neko boosts bob@fedibird's note; boost appears on Fedibird."""
        # alice follows bob so notes federate
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Boost from Neko FB {time.time()}"
        fb_status = fedibird.create_status(unique)

        # Wait for note to federate to Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="fedibird note on neko")

        # alice boosts
        neko.reblog(neko_note["id"])

        # Check boost notification on Fedibird
        def check_boost_on_fedibird():
            notifs = fedibird.get_notifications(limit=20)
            return any(n.get("type") == "reblog" for n in notifs)

        poll_until(check_boost_on_fedibird, desc="boost notification on fedibird")


# ── 12. Favourite (Like) federation ──────────────────────────


class TestFavouriteFederation:
    """Test that favourites/likes federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, fedibird: FedibirdClient):
        if cls._follow_established:
            return
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                fedibird.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_fedibird(self, neko, fedibird, text):
        self._ensure_follow(neko, fedibird)
        note = neko.create_note(text)

        def find_note():
            tl = fedibird.timeline_public()
            for s in tl:
                if text in (s.get("content") or ""):
                    return s
            return None

        fb_status = poll_until(find_note, desc=f"'{text}' on fedibird")
        return note, fb_status

    def test_fedibird_favourites_neko_note(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob@fedibird favourites alice@neko's note; like notification arrives."""
        note, fb_status = self._wait_for_note_on_fedibird(
            neko, fedibird, f"Fav me FB {time.time()}"
        )
        fedibird.favourite(fb_status["id"])

        def check_notification():
            notifs = neko.notifications(limit=20)
            return any(
                n.get("type") in ("favourite", "reaction")
                and n.get("status", {}).get("id") == note["id"]
                for n in notifs
            )

        poll_until(check_notification, timeout=120, desc="favourite notification on neko")

    def test_neko_favourite_federates_to_fedibird(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """alice@neko favourites bob@fedibird's note."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Fav from Neko FB {time.time()}"
        fb_status = fedibird.create_status(unique)

        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="fedibird note on neko")

        # alice favourites
        neko.favourite(neko_note["id"])

        # Check on Fedibird
        def check_fav_on_fedibird():
            notifs = fedibird.get_notifications(limit=20)
            return any(n.get("type") == "favourite" for n in notifs)

        poll_until(check_fav_on_fedibird, desc="favourite notification on fedibird")


# ── 13. Emoji reaction federation (Fedibird extension) ───────


class TestEmojiReactionFederation:
    """Test Fedibird's emoji reaction support with Nekonoverse.

    Both Nekonoverse and Fedibird support non-standard emoji reactions
    beyond the Mastodon favourite (Like) mechanism.
    """

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, fedibird: FedibirdClient):
        if cls._follow_established:
            return
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                fedibird.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_fedibird(self, neko, fedibird, text):
        self._ensure_follow(neko, fedibird)
        note = neko.create_note(text)

        def find_note():
            tl = fedibird.timeline_public()
            for s in tl:
                if text in (s.get("content") or ""):
                    return s
            return None

        fb_status = poll_until(find_note, desc=f"'{text}' on fedibird")
        return note, fb_status

    def test_neko_emoji_reaction_federates_to_fedibird(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """alice@neko sends 👍 reaction to bob's note; notification arrives on Fedibird."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"React me FB {time.time()}"
        fb_status = fedibird.create_status(unique)

        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="fedibird note on neko")

        # alice reacts with 👍
        neko.react(neko_note["id"], "%F0%9F%91%8D")

        # Check notification on Fedibird — may appear as "favourite" or "emoji_reaction"
        def check_reaction_on_fedibird():
            notifs = fedibird.get_notifications(limit=20)
            return any(
                n.get("type") in ("favourite", "emoji_reaction", "reaction")
                for n in notifs
            )

        poll_until(check_reaction_on_fedibird, desc="reaction notification on fedibird")

    def test_fedibird_emoji_reaction_federates_to_neko(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob@fedibird sends emoji reaction to alice's note; notification on Neko."""
        note, fb_status = self._wait_for_note_on_fedibird(
            neko, fedibird, f"React from FB {time.time()}"
        )

        # bob reacts with emoji on Fedibird
        # Fedibird's emoji reaction API endpoint
        try:
            fedibird.emoji_react(fb_status["id"], "👍")
        except Exception:
            # Fallback: Fedibird may use favourite as fallback
            fedibird.favourite(fb_status["id"])

        # Check notification on Neko — emoji reaction or favourite
        def check_reaction_on_neko():
            notifs = neko.notifications(limit=20)
            return any(
                n.get("type") in ("favourite", "reaction")
                and n.get("status", {}).get("id") == note["id"]
                for n in notifs
            )

        poll_until(check_reaction_on_neko, desc="reaction notification on neko")


# ── 14. CW / Sensitive federation ────────────────────────────


class TestSensitiveFederation:
    """Test that content warnings (CW / spoiler_text) federate."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, fedibird: FedibirdClient):
        if cls._follow_established:
            return
        accounts = fedibird.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                fedibird.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_sensitive_note_federates(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """alice creates a CW note; spoiler_text appears on Fedibird."""
        self._ensure_follow(neko, fedibird)
        unique = f"CW body FB {time.time()}"
        neko.create_note(unique, spoiler_text="CW test")

        def check():
            tl = fedibird.timeline_public()
            for s in tl:
                if unique in (s.get("content") or ""):
                    return s.get("spoiler_text") == "CW test"
            return False

        poll_until(check, desc="CW note on fedibird")

    def test_fedibird_sensitive_note_federates(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob creates a CW note on Fedibird; spoiler_text appears on Neko."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"FB CW body {time.time()}"
        fedibird.create_status(unique, spoiler_text="FB CW test")

        def check():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n.get("spoiler_text") == "FB CW test"
            return False

        poll_until(check, desc="CW note on neko")


# ── 15. Hashtag federation ───────────────────────────────────


class TestHashtagFederation:
    """Test that hashtags federate correctly."""

    def test_neko_hashtag_in_ap(self, neko: NekoClient, alice):
        """Neko note with hashtag includes Hashtag tag in AP."""
        note = neko.create_note(f"Testing #nekonoverse hashtag {time.time()}")
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
        )
        assert resp.status_code == 200
        ap_note = resp.json()
        tags = ap_note.get("tag", [])
        hashtag_tags = [t for t in tags if t.get("type") == "Hashtag"]
        assert len(hashtag_tags) >= 1, f"No Hashtag tags in {tags}"
        assert any(
            "nekonoverse" in t.get("name", "").lower() for t in hashtag_tags
        )

    def test_fedibird_hashtag_federates_to_neko(
        self, neko: NekoClient, fedibird: FedibirdClient, alice, bob
    ):
        """bob creates a note with hashtag on Fedibird; it appears on Neko."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{FEDIBIRD_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Hashtag test #fedibird {time.time()}"
        fedibird.create_status(unique)

        def check():
            tl = neko.public_timeline()
            for n in tl:
                content = n.get("content") or ""
                if "Hashtag test" in content and "fedibird" in content.lower():
                    return True
            return False

        poll_until(check, desc="hashtag note on neko")
