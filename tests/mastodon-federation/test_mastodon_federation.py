"""Mastodon cross-platform federation tests.

Tests Nekonoverse <-> Mastodon federation covering:
- Health checks, WebFinger, Actor endpoints
- Note creation and federation
- Follow flow
- Reply federation
- Mention / notification federation
- Delete federation
- Boost (reblog/announce) federation
- Favourite (like) federation
- CW (spoiler_text / sensitive) federation
- Hashtag federation
"""

import time

import httpx
import pytest

from conftest import (
    MASTODON_DOMAIN,
    MASTODON_URL,
    NEKO_DOMAIN,
    NEKO_URL,
    MastodonClient,
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

    def test_mastodon_healthy(self, mastodon: MastodonClient):
        assert mastodon.health() is True


# ── 2. Registration ───────────────────────────────────────────


class TestRegistration:
    def test_alice_registered(self, alice):
        assert alice["username"] == "alice"

    def test_bob_registered(self, bob):
        assert "access_token" in bob or "id" in bob

    def test_bob_credentials(self, mastodon: MastodonClient, bob):
        creds = mastodon.verify_credentials()
        assert creds["username"] == "bob"


# ── 3. WebFinger ──────────────────────────────────────────────


class TestWebFinger:
    def test_neko_webfinger(self, neko: NekoClient, alice):
        result = neko.webfinger(f"alice@{NEKO_DOMAIN}")
        assert result["subject"] == f"acct:alice@{NEKO_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_mastodon_webfinger(self, mastodon: MastodonClient, bob):
        result = mastodon.webfinger(f"bob@{MASTODON_DOMAIN}")
        assert result["subject"] == f"acct:bob@{MASTODON_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_cross_webfinger_neko_from_mastodon(self, alice, bob):
        """Mastodon can resolve Neko's WebFinger."""
        resp = _get(
            f"{NEKO_URL}/.well-known/webfinger",
            params={"resource": f"acct:alice@{NEKO_DOMAIN}"},
        )
        assert resp.status_code == 200

    def test_cross_webfinger_mastodon_from_neko(self, alice, bob):
        """Neko can resolve Mastodon's WebFinger."""
        resp = _get(
            f"{MASTODON_URL}/.well-known/webfinger",
            params={"resource": f"acct:bob@{MASTODON_DOMAIN}"},
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

    def test_mastodon_actor(self, mastodon: MastodonClient, bob):
        """Mastodon actor endpoint returns valid AP Person."""
        wf = mastodon.webfinger(f"bob@{MASTODON_DOMAIN}")
        actor_url = None
        for link in wf["links"]:
            if link.get("rel") == "self":
                actor_url = link["href"]
                break
        assert actor_url is not None
        actor = mastodon.get_actor_ap(actor_url)
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
        note = neko.create_note("Hello from Nekonoverse for Mastodon test!")
        assert note["content"] is not None
        assert note["actor"]["username"] == "alice"

    def test_mastodon_create_status(self, mastodon: MastodonClient, bob):
        status = mastodon.create_status("Hello from Mastodon for federation test!")
        assert status["content"] is not None

    def test_neko_note_ap_format(self, neko: NekoClient, alice):
        """Neko note AP representation is Mastodon-compatible."""
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

    def test_mastodon_nodeinfo(self, bob):
        resp = _get(f"{MASTODON_URL}/.well-known/nodeinfo")
        assert resp.status_code == 200
        data = resp.json()
        assert "links" in data
        link_url = data["links"][0]["href"]
        resp2 = _get(link_url)
        assert resp2.status_code == 200
        ni = resp2.json()
        assert ni["software"]["name"] == "mastodon"


# ── 7. Follow federation ─────────────────────────────────────


class TestFollowFederation:
    """Test follow flow between Mastodon and Nekonoverse."""

    def test_mastodon_resolves_neko_user(self, mastodon: MastodonClient, alice, bob):
        """Bob on Mastodon resolves alice@nekonoverse."""
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        assert len(accounts) > 0
        assert accounts[0]["username"] == "alice"

    def test_mastodon_follows_neko_user(self, mastodon: MastodonClient, alice, bob):
        """Bob on Mastodon follows alice@nekonoverse."""
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        assert len(accounts) > 0
        result = mastodon.follow(accounts[0]["id"])
        assert result is not None

    def test_neko_receives_follower(self, neko: NekoClient, alice, bob):
        """Alice has bob@mastodon as a follower."""
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

    def test_neko_note_federates_to_mastodon(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """Note by alice on Neko appears on Mastodon's public timeline."""
        unique = f"Fed note to Mastodon {time.time()}"
        neko.create_note(unique)

        def check():
            tl = mastodon.timeline_public()
            return any(unique in (s.get("content") or "") for s in tl)

        poll_until(check, desc="neko note on mastodon")


# ── 8. Reply federation ──────────────────────────────────────


class TestReplyFederation:
    """Test reply federation between Mastodon and Nekonoverse."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, mastodon: MastodonClient):
        if cls._follow_established:
            return
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                mastodon.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_mastodon(self, neko: NekoClient, mastodon: MastodonClient, text: str):
        """Create a note on Neko and wait for it to appear on Mastodon."""
        self._ensure_follow(neko, mastodon)
        note = neko.create_note(text)

        def find_note():
            tl = mastodon.timeline_public()
            for s in tl:
                if text in (s.get("content") or ""):
                    return s
            return None

        mdn_status = poll_until(find_note, desc=f"'{text}' on mastodon")
        return note, mdn_status

    def test_mastodon_reply_to_neko_note(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """bob@mastodon replies to alice@neko's note; reply federates back."""
        note, mdn_status = self._wait_for_note_on_mastodon(
            neko, mastodon, f"Reply target {time.time()}"
        )
        mastodon.create_status(
            f"Reply from Mastodon {time.time()}", in_reply_to_id=mdn_status["id"]
        )

        def check_reply():
            n = neko.get_note(note["id"])
            return n.get("replies_count", 0) >= 1

        poll_until(check_reply, desc="reply federated to neko")

    def test_neko_reply_to_mastodon_note(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """alice@neko replies to bob@mastodon's note."""
        # alice follows bob so notes federate
        results = neko.search_accounts(f"bob@{MASTODON_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Reply me from Neko {time.time()}"
        mdn_status = mastodon.create_status(unique)

        # Wait for note to appear on Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="mastodon note on neko")

        # alice replies
        reply_text = f"Neko reply {time.time()}"
        neko.create_note(reply_text, in_reply_to_id=neko_note["id"])

        # Check reply on Mastodon
        def check_reply_on_mastodon():
            ctx = mastodon.get_context(mdn_status["id"])
            return any(reply_text in (r.get("content") or "") for r in ctx.get("descendants", []))

        poll_until(check_reply_on_mastodon, desc="neko reply on mastodon")

    def test_reply_thread_context(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """Reply chain creates a proper thread context on Neko."""
        note, mdn_status = self._wait_for_note_on_mastodon(
            neko, mastodon, f"Thread ctx {time.time()}"
        )
        mastodon.create_status(
            f"Reply in thread {time.time()}", in_reply_to_id=mdn_status["id"]
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
    def _ensure_follow(cls, neko: NekoClient, mastodon: MastodonClient):
        if cls._follow_established:
            return
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                mastodon.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_mentions_mastodon_user(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """alice@neko creates a note mentioning @bob@mastodon."""
        results = neko.search_accounts(f"bob@{MASTODON_DOMAIN}", resolve=True)
        assert len(results) > 0

        unique = f"Hey @bob@{MASTODON_DOMAIN} check this {time.time()}"
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

    def test_mastodon_mentions_neko_user(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """bob@mastodon mentions @alice@nekonoverse; alice should get a notification."""
        self._ensure_follow(neko, mastodon)

        unique = f"Hey @alice@{NEKO_DOMAIN} look {time.time()}"
        mastodon.create_status(unique)

        def check_mention_notification():
            notifs = neko.notifications(limit=30)
            return any(n.get("type") == "mention" for n in notifs)

        poll_until(check_mention_notification, desc="mention notification on neko")


# ── 10. Delete federation ────────────────────────────────────


class TestDeleteFederation:
    """Test that note deletions federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, mastodon: MastodonClient):
        if cls._follow_established:
            return
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                mastodon.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_deletes_note_federates_to_mastodon(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """alice deletes a note; it should disappear from Mastodon."""
        self._ensure_follow(neko, mastodon)
        unique = f"Delete me {time.time()}"
        note = neko.create_note(unique)

        # Wait for note on Mastodon
        def find_note():
            tl = mastodon.timeline_public()
            for s in tl:
                if unique in (s.get("content") or ""):
                    return s
            return None

        mdn_status = poll_until(find_note, desc="note on mastodon")

        # Delete on Neko
        neko.delete_note(note["id"])

        # Wait for deletion to federate
        def check_deleted():
            try:
                mastodon.get_status(mdn_status["id"])
                return False  # Still exists
            except Exception:
                return True  # Deleted (404)

        poll_until(check_deleted, desc="deletion federated to mastodon")

    def test_mastodon_deletes_note_federates_to_neko(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """bob deletes a note; it should disappear from Neko."""
        # alice follows bob so notes federate
        results = neko.search_accounts(f"bob@{MASTODON_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"MDN delete me {time.time()}"
        mdn_status = mastodon.create_status(unique)

        # Wait for note on Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="mastodon note on neko")

        # Delete on Mastodon
        mastodon.delete_status(mdn_status["id"])

        # Wait for deletion to federate
        def check_deleted():
            try:
                neko.get_note(neko_note["id"])
                return False
            except Exception:
                return True

        poll_until(check_deleted, desc="mastodon deletion federated to neko")


# ── 11. Boost (Announce) federation ──────────────────────────


class TestBoostFederation:
    """Test that boosts/reblogs federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, mastodon: MastodonClient):
        if cls._follow_established:
            return
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                mastodon.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_mastodon(self, neko, mastodon, text):
        self._ensure_follow(neko, mastodon)
        note = neko.create_note(text)

        def find_note():
            tl = mastodon.timeline_public()
            for s in tl:
                if text in (s.get("content") or ""):
                    return s
            return None

        mdn_status = poll_until(find_note, desc=f"'{text}' on mastodon")
        return note, mdn_status

    def test_mastodon_boosts_neko_note(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """bob@mastodon boosts alice@neko's note; renotes_count increases."""
        note, mdn_status = self._wait_for_note_on_mastodon(
            neko, mastodon, f"Boost me {time.time()}"
        )
        mastodon.reblog(mdn_status["id"])

        def check_count():
            n = neko.get_note(note["id"])
            return n.get("renotes_count", 0) >= 1

        poll_until(check_count, desc="renotes_count >= 1")

    def test_mastodon_boost_creates_notification_on_neko(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """Boost from Mastodon creates a notification for the original author."""
        note, mdn_status = self._wait_for_note_on_mastodon(
            neko, mastodon, f"Boost notif {time.time()}"
        )
        mastodon.reblog(mdn_status["id"])

        def check_notification():
            notifs = neko.notifications(limit=20)
            return any(
                n.get("type") == "renote" and n.get("status", {}).get("id") == note["id"]
                for n in notifs
            )

        poll_until(check_notification, desc="boost notification on neko")

    def test_neko_boost_federates_to_mastodon(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """alice@neko boosts bob@mastodon's note; boost appears on Mastodon."""
        # alice follows bob so notes federate
        results = neko.search_accounts(f"bob@{MASTODON_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Boost from Neko {time.time()}"
        mdn_status = mastodon.create_status(unique)

        # Wait for note to federate to Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="mastodon note on neko")

        # alice boosts
        neko.reblog(neko_note["id"])

        # Check boost notification on Mastodon
        def check_boost_on_mastodon():
            notifs = mastodon.get_notifications(limit=20)
            return any(n.get("type") == "reblog" for n in notifs)

        poll_until(check_boost_on_mastodon, desc="boost notification on mastodon")


# ── 12. Favourite (Like) federation ──────────────────────────


class TestFavouriteFederation:
    """Test that favourites/likes federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, mastodon: MastodonClient):
        if cls._follow_established:
            return
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                mastodon.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_mastodon(self, neko, mastodon, text):
        self._ensure_follow(neko, mastodon)
        note = neko.create_note(text)

        def find_note():
            tl = mastodon.timeline_public()
            for s in tl:
                if text in (s.get("content") or ""):
                    return s
            return None

        mdn_status = poll_until(find_note, desc=f"'{text}' on mastodon")
        return note, mdn_status

    def test_mastodon_favourites_neko_note(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """bob@mastodon favourites alice@neko's note; like notification arrives."""
        note, mdn_status = self._wait_for_note_on_mastodon(
            neko, mastodon, f"Fav me {time.time()}"
        )
        mastodon.favourite(mdn_status["id"])

        def check_notification():
            notifs = neko.notifications(limit=20)
            return any(
                n.get("type") == "favourite" and n.get("status", {}).get("id") == note["id"]
                for n in notifs
            )

        poll_until(check_notification, desc="favourite notification on neko")

    def test_neko_favourite_federates_to_mastodon(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """alice@neko favourites bob@mastodon's note."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{MASTODON_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Fav from Neko {time.time()}"
        mdn_status = mastodon.create_status(unique)

        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, desc="mastodon note on neko")

        # alice favourites
        neko.favourite(neko_note["id"])

        # Check on Mastodon
        def check_fav_on_mastodon():
            notifs = mastodon.get_notifications(limit=20)
            return any(n.get("type") == "favourite" for n in notifs)

        poll_until(check_fav_on_mastodon, desc="favourite notification on mastodon")


# ── 13. CW / Sensitive federation ────────────────────────────


class TestSensitiveFederation:
    """Test that content warnings (CW / spoiler_text) federate."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, mastodon: MastodonClient):
        if cls._follow_established:
            return
        accounts = mastodon.search_accounts(f"alice@{NEKO_DOMAIN}", resolve=True)
        if accounts:
            try:
                mastodon.follow(accounts[0]["id"])
            except Exception:
                pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_sensitive_note_federates(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """alice creates a CW note; spoiler_text appears on Mastodon."""
        self._ensure_follow(neko, mastodon)
        unique = f"CW body {time.time()}"
        neko.create_note(unique, spoiler_text="CW test")

        def check():
            tl = mastodon.timeline_public()
            for s in tl:
                if unique in (s.get("content") or ""):
                    return s.get("spoiler_text") == "CW test"
            return False

        poll_until(check, desc="CW note on mastodon")

    def test_mastodon_sensitive_note_federates(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """bob creates a CW note on Mastodon; spoiler_text appears on Neko."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{MASTODON_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"MDN CW body {time.time()}"
        mastodon.create_status(unique, spoiler_text="MDN CW test")

        def check():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n.get("spoiler_text") == "MDN CW test"
            return False

        poll_until(check, desc="CW note on neko")


# ── 14. Hashtag federation ───────────────────────────────────


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

    def test_mastodon_hashtag_federates_to_neko(
        self, neko: NekoClient, mastodon: MastodonClient, alice, bob
    ):
        """bob creates a note with hashtag on Mastodon; it appears on Neko."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{MASTODON_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Hashtag test #mastodon {time.time()}"
        mastodon.create_status(unique)

        def check():
            tl = neko.public_timeline()
            for n in tl:
                content = n.get("content") or ""
                if "Hashtag test" in content and "mastodon" in content.lower():
                    return True
            return False

        poll_until(check, desc="hashtag note on neko")
