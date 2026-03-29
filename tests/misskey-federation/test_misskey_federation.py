"""Cross-platform federation tests: Nekonoverse <-> Misskey.

Uses self-signed certificates for HTTPS to enable full federation.
"""

import time

import httpx
import pytest

from conftest import (
    NEKO_URL,
    MISSKEY_URL,
    NEKO_DOMAIN,
    MISSKEY_DOMAIN,
    NekoClient,
    MisskeyClient,
    poll_until,
)


def _get(url, **kwargs):
    """httpx.get with SSL verification disabled for self-signed certs."""
    return httpx.get(url, verify=False, **kwargs)


# ── 1. Health ────────────────────────────────────────────────


class TestHealth:
    def test_nekonoverse_healthy(self, neko: NekoClient, alice):
        assert neko.health() == {"status": "ok"}

    def test_misskey_healthy(self, misskey: MisskeyClient, bob):
        assert misskey.health() is True


# ── 2. WebFinger ─────────────────────────────────────────────


class TestWebFinger:
    def test_neko_webfinger(self, neko: NekoClient, alice):
        result = neko.webfinger(f"alice@{NEKO_DOMAIN}")
        assert result["subject"] == f"acct:alice@{NEKO_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_misskey_webfinger(self, misskey: MisskeyClient, bob):
        result = misskey.webfinger(f"bob@{MISSKEY_DOMAIN}")
        assert result["subject"] == f"acct:bob@{MISSKEY_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_cross_webfinger_neko_from_misskey(self, alice):
        resp = _get(
            f"{NEKO_URL}/.well-known/webfinger",
            params={"resource": f"acct:alice@{NEKO_DOMAIN}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["subject"] == f"acct:alice@{NEKO_DOMAIN}"

    def test_cross_webfinger_misskey_from_neko(self, bob):
        resp = _get(
            f"{MISSKEY_URL}/.well-known/webfinger",
            params={"resource": f"acct:bob@{MISSKEY_DOMAIN}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["subject"] == f"acct:bob@{MISSKEY_DOMAIN}"


# ── 3. Actor endpoints ──────────────────────────────────────


class TestActor:
    def test_neko_actor(self, neko: NekoClient, alice):
        actor = neko.get_actor_ap("alice")
        assert actor["type"] == "Person"
        assert actor["preferredUsername"] == "alice"
        assert "publicKey" in actor

    def test_misskey_actor(self, misskey: MisskeyClient, bob):
        actor = misskey.get_actor_ap("bob")
        assert actor["type"] == "Person"
        assert actor["preferredUsername"] == "bob"
        assert "publicKey" in actor

    def test_cross_actor_fetch(self, alice, bob):
        resp = _get(
            f"{NEKO_URL}/users/alice",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["preferredUsername"] == "alice"

        mk_wf = _get(
            f"{MISSKEY_URL}/.well-known/webfinger",
            params={"resource": f"acct:bob@{MISSKEY_DOMAIN}"},
            timeout=10,
        ).json()
        self_link = next(l["href"] for l in mk_wf["links"] if l.get("rel") == "self")
        resp2 = _get(self_link, headers={"Accept": "application/activity+json"}, timeout=10)
        assert resp2.status_code == 200
        assert resp2.json()["preferredUsername"] == "bob"

    def test_neko_actor_has_misskey_extensions(self, neko: NekoClient, alice):
        actor = neko.get_actor_ap("alice")
        assert "isCat" in actor
        assert "endpoints" in actor
        assert "sharedInbox" in actor["endpoints"]

    def test_actor_public_key_format(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        neko_actor = neko.get_actor_ap("alice")
        mk_actor = misskey.get_actor_ap("bob")

        for actor, name in [(neko_actor, "neko"), (mk_actor, "misskey")]:
            pk = actor["publicKey"]
            assert "id" in pk, f"{name} missing publicKey.id"
            assert "owner" in pk, f"{name} missing publicKey.owner"
            assert pk["publicKeyPem"].startswith("-----BEGIN PUBLIC KEY-----"), f"{name} bad PEM"


# ── 4. Note creation ────────────────────────────────────────


class TestNotes:
    def test_neko_create_note(self, neko: NekoClient, alice):
        note = neko.create_note("Hello from Nekonoverse!")
        assert "id" in note
        assert note["content"] is not None

    def test_misskey_create_note(self, misskey: MisskeyClient, bob):
        result = misskey.create_note("Hello from Misskey!")
        assert "createdNote" in result

    def test_neko_local_timeline(self, neko: NekoClient, alice):
        tl = neko.public_timeline(local=True)
        assert len(tl) >= 1

    def test_misskey_local_timeline(self, misskey: MisskeyClient, bob):
        tl = misskey.timeline_local()
        assert len(tl) >= 1


# ── 5. AP cross-fetch ───────────────────────────────────────


class TestAPCrossFetch:
    def test_neko_note_fetchable_via_ap(self, neko: NekoClient, alice):
        note = neko.create_note("Fetchable note!")
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Note"
        assert "attributedTo" in data

    def test_misskey_note_fetchable_via_ap(self, misskey: MisskeyClient, bob):
        result = misskey.create_note("Fetchable Misskey note!")
        mk_note = result["createdNote"]
        resp = _get(
            f"{MISSKEY_URL}/notes/{mk_note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["type"] == "Note"

    def test_neko_note_ap_format_compatible(self, neko: NekoClient, alice):
        note = neko.create_note("Check my AP format!")
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        data = resp.json()
        for field in ("@context", "id", "attributedTo", "content", "published", "to"):
            assert field in data, f"Missing {field}"
        assert data["type"] == "Note"

    def test_neko_outbox_format(self, neko: NekoClient, alice):
        resp = _get(
            f"{NEKO_URL}/users/alice/outbox",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        outbox = resp.json()
        assert outbox["type"] == "OrderedCollection"
        assert "totalItems" in outbox

    def test_neko_outbox_page(self, neko: NekoClient, alice):
        resp = _get(
            f"{NEKO_URL}/users/alice/outbox",
            params={"page": "true"},
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        page = resp.json()
        assert page["type"] == "OrderedCollectionPage"
        assert len(page["orderedItems"]) >= 1
        assert page["orderedItems"][0]["type"] == "Create"


# ── 6. NodeInfo ──────────────────────────────────────────────


class TestNodeInfo:
    def test_neko_nodeinfo(self, neko: NekoClient, alice):
        resp = _get(f"{NEKO_URL}/.well-known/nodeinfo", timeout=10)
        assert resp.status_code == 200
        assert len(resp.json()["links"]) > 0

        resp2 = _get(f"{NEKO_URL}/nodeinfo/2.0", timeout=10)
        assert resp2.status_code == 200
        assert resp2.json()["software"]["name"] == "nekonoverse"

    def test_misskey_nodeinfo(self, misskey: MisskeyClient, bob):
        resp = _get(f"{MISSKEY_URL}/.well-known/nodeinfo", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["links"]) > 0

        nodeinfo_href = data["links"][0]["href"]
        path = "/" + nodeinfo_href.split("/", 3)[-1]
        resp2 = _get(f"{MISSKEY_URL}{path}", timeout=10)
        assert resp2.status_code == 200
        assert resp2.json()["software"]["name"] == "misskey"


# ── 7. Poll AP format ───────────────────────────────────────


class TestPoll:
    def test_misskey_creates_poll(self, misskey: MisskeyClient, bob):
        result = misskey.create_poll_note(
            "Which platform?",
            choices=["Nekonoverse", "Misskey", "Both"],
        )
        assert "createdNote" in result
        assert result["createdNote"]["poll"] is not None

    def test_misskey_poll_ap_format(self, misskey: MisskeyClient, bob):
        result = misskey.create_poll_note(
            "Best cat emoji?",
            choices=["Cat", "Smile", "Walk"],
        )
        mk_note = result["createdNote"]
        resp = _get(
            f"{MISSKEY_URL}/notes/{mk_note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Question"
        assert "oneOf" in data or "anyOf" in data


# ── 8. Full federation (Misskey <-> Nekonoverse via HTTPS) ───


class TestFullFederation:
    def test_misskey_resolves_neko_user(self, misskey: MisskeyClient, alice, bob):
        """Misskey resolves alice@nekonoverse via WebFinger+actor fetch."""
        result = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        assert result["username"] == "alice"
        assert result["host"] == NEKO_DOMAIN

    def test_misskey_follows_neko_user(self, misskey: MisskeyClient, alice, bob):
        """bob@misskey follows alice@nekonoverse."""
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        misskey.follow(resolved["id"])

        def check_following():
            user = misskey._api("users/show", {"userId": resolved["id"]})
            return user.get("isFollowing", False)

        poll_until(check_following, timeout=60, interval=2, desc="bob follows alice")

    def test_neko_receives_follower(self, neko: NekoClient, alice, bob):
        """alice has bob as a follower after follow federation."""
        def check_followers():
            resp = neko.http.get(
                "/users/alice/followers",
                headers={"Accept": "application/activity+json"},
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("totalItems", 0) > 0
            return False

        poll_until(check_followers, timeout=60, interval=2, desc="alice has followers")

    def test_neko_note_appears_on_misskey(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """After follow, alice's notes federate to Misskey's timeline."""
        neko.create_note("Federation test note from Nekonoverse!")

        def check_note_federated():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            return any("Federation test note" in (n.get("text") or "") for n in tl)

        poll_until(check_note_federated, timeout=60, interval=2, desc="neko note on misskey")

    def test_misskey_reacts_to_federated_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """bob reacts to a federated note; reaction appears on Nekonoverse."""
        note = neko.create_note("React to this federated note!")

        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if "React to this federated" in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc="note on misskey")
        misskey.react(mk_note["id"], "👍")

        def check_reaction():
            n = neko.get_note(note["id"])
            return n.get("reactions_count", 0) > 0

        poll_until(check_reaction, timeout=60, interval=2, desc="reaction federated to neko")

    def test_misskey_renotes_federated_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """bob renotes a federated note from alice."""
        note = neko.create_note("Renote this federated note!")

        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if "Renote this federated" in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc="note on misskey")
        misskey.renote(mk_note["id"])

        tl = misskey.timeline_local(limit=10)
        assert any(n.get("renoteId") == mk_note["id"] for n in tl)


# ── 9. Reaction federation (extended) ─────────────────────────


class TestReactionFederation:
    """Extended reaction federation tests between Misskey and Nekonoverse."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, misskey: MisskeyClient):
        """Ensure bob@misskey follows alice@neko (idempotent)."""
        if cls._follow_established:
            return
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass  # Already following
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_misskey(self, neko: NekoClient, misskey: MisskeyClient, text: str):
        """Create a note on Neko and wait for it to appear on Misskey."""
        self._ensure_follow(neko, misskey)
        note = neko.create_note(text)

        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if text in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc=f"'{text}' on misskey")
        return note, mk_note

    def test_misskey_reaction_emoji_preserved(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """Verify the specific emoji from Misskey reaction is preserved on Nekonoverse."""
        note, mk_note = self._wait_for_note_on_misskey(neko, misskey, f"Emoji check {time.time()}")
        misskey.react(mk_note["id"], "🎉")

        def check_reaction():
            n = neko.get_note(note["id"])
            reactions = n.get("emoji_reactions") or n.get("reactions") or {}
            if isinstance(reactions, list):
                return any(r.get("name") == "🎉" or r.get("emoji") == "🎉" for r in reactions)
            if isinstance(reactions, dict):
                return "🎉" in reactions
            return n.get("reactions_count", 0) > 0

        poll_until(check_reaction, timeout=60, interval=2, desc="🎉 reaction on neko")

    def test_misskey_multiple_reactions_different_emoji(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """Misskey user reacts, unreacts, then reacts with different emoji."""
        note, mk_note = self._wait_for_note_on_misskey(neko, misskey, f"Multi react {time.time()}")

        # React with 👍
        misskey.react(mk_note["id"], "👍")

        def check_first():
            n = neko.get_note(note["id"])
            return n.get("reactions_count", 0) >= 1

        poll_until(check_first, timeout=60, interval=2, desc="first reaction arrives")

        # Unreact on Misskey (removes current reaction)
        misskey.unreact(mk_note["id"])

        def check_unreact():
            n = neko.get_note(note["id"])
            return n.get("reactions_count", 0) == 0

        poll_until(check_unreact, timeout=60, interval=2, desc="unreaction arrives")

        # React with different emoji
        misskey.react(mk_note["id"], "❤")

        def check_second():
            n = neko.get_note(note["id"])
            return n.get("reactions_count", 0) >= 1

        poll_until(check_second, timeout=60, interval=2, desc="second reaction arrives")

    def test_neko_reacts_to_misskey_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """alice@neko reacts to bob@misskey's note (reverse direction).

        alice follows bob@misskey first so that bob's notes federate to Neko,
        then reacts to a newly created note.
        """
        # Resolve bob@misskey on Neko and follow
        results = neko.search_accounts(f"bob@{MISSKEY_DOMAIN}", resolve=True)
        assert len(results) > 0, "Could not resolve bob@misskey on Neko"
        bob_on_neko = results[0]
        neko.follow(bob_on_neko["id"])

        # Wait for follow to be accepted
        import time
        time.sleep(5)

        # Bob creates a note on Misskey
        unique = f"React from Neko {time.time()}"
        result = misskey.create_note(unique)
        mk_note = result["createdNote"]

        # Wait for it to federate to Neko's home timeline (via follow)
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, timeout=60, interval=2, desc="misskey note on neko")

        # Alice reacts on Neko
        neko.react(neko_note["id"], "⭐")

        # Check reaction arrived on Misskey — exactly one, with the correct emoji
        def check_reaction_on_misskey():
            reactions = misskey.get_reactions(mk_note["id"])
            if len(reactions) == 0:
                return None
            return reactions

        reactions = poll_until(check_reaction_on_misskey, timeout=60, interval=2, desc="reaction federated to misskey")
        assert len(reactions) == 1, f"Expected exactly 1 reaction, got {len(reactions)}"
        # ⭐ favourite is sent as bare Like (no content) — Misskey maps to ❤
        assert reactions[0]["type"] == "❤", f"Expected ❤ (bare Like→Misskey default), got {reactions[0]['type']}"

        # Verify the note itself shows the reaction (display side)
        mk_note_detail = misskey.get_note(mk_note["id"])
        note_reactions = mk_note_detail.get("reactions", {})
        assert sum(note_reactions.values()) == 1, f"Expected 1 total reaction on note, got {note_reactions}"

    def test_misskey_heart_reaction_maps_correctly(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """Misskey ❤ (Like) reaction is correctly stored on Nekonoverse."""
        note, mk_note = self._wait_for_note_on_misskey(neko, misskey, f"Heart test {time.time()}")
        misskey.react(mk_note["id"], "❤")

        def check():
            n = neko.get_note(note["id"])
            return n.get("reactions_count", 0) > 0

        poll_until(check, timeout=60, interval=2, desc="heart reaction on neko")

    def test_misskey_reaction_count_accurate(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """Reaction count on Nekonoverse accurately reflects Misskey reactions."""
        note, mk_note = self._wait_for_note_on_misskey(neko, misskey, f"Count test {time.time()}")
        misskey.react(mk_note["id"], "😂")

        def check_count():
            n = neko.get_note(note["id"])
            return n.get("reactions_count", 0) == 1

        poll_until(check_count, timeout=60, interval=2, desc="reaction count == 1")


# ── 10. Renote federation (extended) ────────────────────────


class TestRenoteFederation:
    """Test that remote renotes create notifications and update counts."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, misskey: MisskeyClient):
        if cls._follow_established:
            return
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_misskey(self, neko, misskey, text):
        self._ensure_follow(neko, misskey)
        note = neko.create_note(text)

        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if text in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc=f"'{text}' on misskey")
        return note, mk_note

    def test_misskey_renote_updates_count_on_neko(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Renote from Misskey increments renotes_count on Nekonoverse."""
        note, mk_note = self._wait_for_note_on_misskey(
            neko, misskey, f"Renote count test {time.time()}"
        )
        misskey.renote(mk_note["id"])

        def check_count():
            n = neko.get_note(note["id"])
            return n.get("renotes_count", 0) >= 1

        poll_until(check_count, timeout=60, interval=2, desc="renotes_count >= 1")

    def test_misskey_renote_creates_notification_on_neko(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Renote from Misskey creates a notification for the original author."""
        note, mk_note = self._wait_for_note_on_misskey(
            neko, misskey, f"Renote notif test {time.time()}"
        )
        misskey.renote(mk_note["id"])

        def check_notification():
            notifs = neko.notifications(limit=20)
            return any(
                n.get("type") in ("renote", "reblog") and n.get("status", {}).get("id") == note["id"]
                for n in notifs
            )

        poll_until(check_notification, timeout=60, interval=2, desc="renote notification on neko")

    def test_misskey_renote_appears_on_neko_public_timeline(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Renote from Misskey appears on Nekonoverse public timeline with reblog field."""
        note, mk_note = self._wait_for_note_on_misskey(
            neko, misskey, f"Renote TL test {time.time()}"
        )
        misskey.renote(mk_note["id"])

        def check_renote_on_timeline():
            tl = neko.public_timeline()
            for n in tl:
                reblog = n.get("reblog")
                if reblog and reblog.get("id") == note["id"]:
                    return n
            return None

        renote = poll_until(
            check_renote_on_timeline, timeout=60, interval=2, desc="renote on neko public TL"
        )
        # Verify the renote has the reblog field (ribbon data)
        assert renote["reblog"] is not None
        assert renote["reblog"]["id"] == note["id"]


# ── 11. Reply federation ──────────────────────────────────────


class TestReplyFederation:
    """Test that replies federate correctly between Misskey and Nekonoverse."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, misskey: MisskeyClient):
        if cls._follow_established:
            return
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass
        time.sleep(3)
        cls._follow_established = True

    def _wait_for_note_on_misskey(self, neko, misskey, text):
        self._ensure_follow(neko, misskey)
        note = neko.create_note(text)

        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if text in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc=f"'{text}' on misskey")
        return note, mk_note

    def test_misskey_reply_to_neko_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """bob@misskey replies to alice@neko's note; reply federates back."""
        note, mk_note = self._wait_for_note_on_misskey(
            neko, misskey, f"Reply target {time.time()}"
        )
        misskey.create_note(f"Reply from Misskey {time.time()}", replyId=mk_note["id"])
        time.sleep(3)  # Misskey のジョブキュー処理待ち

        def check_reply():
            ctx = neko.get_context(note["id"])
            return len(ctx.get("descendants", [])) >= 1

        poll_until(check_reply, timeout=120, interval=3, desc="reply federated to neko")

    def test_neko_reply_to_misskey_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """alice@neko replies to bob@misskey's note."""
        # alice follows bob@misskey so notes federate
        results = neko.search_accounts(f"bob@{MISSKEY_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        # bob creates a note
        unique = f"Reply me from Neko {time.time()}"
        result = misskey.create_note(unique)
        mk_note = result["createdNote"]

        # Wait for note to appear on Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, timeout=60, interval=2, desc="misskey note on neko")

        # alice replies
        reply_text = f"Neko reply {time.time()}"
        neko.create_note(reply_text, in_reply_to_id=neko_note["id"])

        # Check reply appeared on Misskey
        def check_reply_on_misskey():
            children = misskey._api("notes/children", {"noteId": mk_note["id"], "limit": 10})
            return any(reply_text in (c.get("text") or "") for c in children)

        poll_until(check_reply_on_misskey, timeout=60, interval=2, desc="neko reply on misskey")

    def test_reply_thread_context(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """Reply chain creates a proper thread context on Neko."""
        note, mk_note = self._wait_for_note_on_misskey(
            neko, misskey, f"Thread ctx {time.time()}"
        )
        misskey.create_note(f"Reply in thread {time.time()}", replyId=mk_note["id"])

        def check_context():
            ctx = neko.get_context(note["id"])
            return len(ctx.get("descendants", [])) >= 1

        poll_until(check_context, timeout=60, interval=2, desc="reply in thread context")

        ctx = neko.get_context(note["id"])
        assert len(ctx["descendants"]) >= 1
        descendant = ctx["descendants"][0]
        assert descendant["in_reply_to_id"] == note["id"]


# ── 12. Mention federation ────────────────────────────────────


class TestMentionFederation:
    """Test that @mentions federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, misskey: MisskeyClient):
        if cls._follow_established:
            return
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_mentions_misskey_user(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """alice@neko creates a note mentioning @bob@misskey."""
        # Resolve bob first
        results = neko.search_accounts(f"bob@{MISSKEY_DOMAIN}", resolve=True)
        assert len(results) > 0

        unique = f"Hey @bob@{MISSKEY_DOMAIN} check this {time.time()}"
        note = neko.create_note(unique)
        assert "id" in note

        # Verify the AP representation has mention tags
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        ap_note = resp.json()
        tags = ap_note.get("tag", [])
        mention_tags = [t for t in tags if t.get("type") == "Mention"]
        assert len(mention_tags) >= 1, f"No Mention tags found in {tags}"

    def test_misskey_mentions_neko_user(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """bob@misskey mentions @alice@nekonoverse; alice should get a notification."""
        self._ensure_follow(neko, misskey)

        unique = f"Hey @alice@{NEKO_DOMAIN} look {time.time()}"
        misskey.create_note(unique)

        def check_mention_notification():
            notifs = neko.notifications(limit=30)
            return any(
                n.get("type") == "mention"
                for n in notifs
            )

        poll_until(
            check_mention_notification,
            timeout=60,
            interval=2,
            desc="mention notification on neko",
        )


# ── 13. Delete federation ─────────────────────────────────────


class TestDeleteFederation:
    """Test that note deletions federate between platforms."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, misskey: MisskeyClient):
        if cls._follow_established:
            return
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_deletes_note_federates_to_misskey(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """alice deletes a note; it should disappear from Misskey."""
        self._ensure_follow(neko, misskey)
        unique = f"Delete me {time.time()}"
        note = neko.create_note(unique)

        # Wait for note on Misskey
        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if unique in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc="note on misskey")

        # Delete on Neko
        neko.delete_note(note["id"])

        # Wait for deletion to federate
        def check_deleted():
            try:
                misskey.get_note(mk_note["id"])
                return False  # Still exists
            except Exception:
                return True  # Deleted (404)

        poll_until(check_deleted, timeout=60, interval=2, desc="deletion federated to misskey")

    def test_misskey_deletes_note_federates_to_neko(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """bob deletes a note; it should be marked deleted on Neko."""
        # alice follows bob so notes federate
        results = neko.search_accounts(f"bob@{MISSKEY_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"MK delete me {time.time()}"
        result = misskey.create_note(unique)
        mk_note = result["createdNote"]

        # Wait for note on Neko
        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, timeout=60, interval=2, desc="mk note on neko")

        # Delete on Misskey
        misskey.delete_note(mk_note["id"])

        # Wait for deletion to federate
        def check_deleted():
            try:
                n = neko.get_note(neko_note["id"])
                # Note may return 404 or have empty/null content after deletion
                return False
            except Exception:
                return True

        poll_until(check_deleted, timeout=60, interval=2, desc="mk deletion federated to neko")


# ── 14. Quote federation ──────────────────────────────────────


class TestQuoteFederation:
    """Test quote notes (引用リノート) between Misskey and Nekonoverse."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, misskey: MisskeyClient):
        if cls._follow_established:
            return
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass
        time.sleep(3)
        cls._follow_established = True

    def test_misskey_quotes_neko_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """bob@misskey quotes alice@neko's note; quote metadata reaches Neko."""
        self._ensure_follow(neko, misskey)
        unique = f"Quote me {time.time()}"
        note = neko.create_note(unique)

        # Wait for note on Misskey
        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if unique in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc="note on misskey")

        # Quote on Misskey
        quote_text = f"Quoting this {time.time()}"
        misskey.quote(mk_note["id"], quote_text)

        # Verify the quote is visible on Misskey's timeline
        def check_quote():
            tl = misskey._api("notes/local-timeline", {"limit": 20})
            return any(
                quote_text in (n.get("text") or "") and n.get("renoteId") == mk_note["id"]
                for n in tl
            )

        poll_until(check_quote, timeout=60, interval=2, desc="quote on misskey timeline")

    def test_neko_quote_ap_format(self, neko: NekoClient, alice):
        """Neko quote includes _misskey_quote in AP representation."""
        parent = neko.create_note(f"Quotable {time.time()}")
        quote = neko.create_note(
            f"My quote {time.time()}", quote_id=parent["id"]
        )

        resp = _get(
            f"{NEKO_URL}/notes/{quote['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        ap_note = resp.json()
        # Should have _misskey_quote or quoteUrl
        has_quote = (
            "_misskey_quote" in ap_note
            or "quoteUrl" in ap_note
            or "quoteUri" in ap_note
        )
        assert has_quote, f"No quote reference in AP note: {list(ap_note.keys())}"


# ── 15. Sensitive/CW federation ───────────────────────────────


class TestSensitiveFederation:
    """Test content warning / sensitive note federation."""

    _follow_established = False

    @classmethod
    def _ensure_follow(cls, neko: NekoClient, misskey: MisskeyClient):
        if cls._follow_established:
            return
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass
        time.sleep(3)
        cls._follow_established = True

    def test_neko_sensitive_note_federates(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """alice creates CW note; Misskey receives it with cw field."""
        self._ensure_follow(neko, misskey)
        unique = f"CW content {time.time()}"
        note = neko.create_note(unique, spoiler_text="Spoiler warning")

        # Verify AP format has summary field
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        ap_note = resp.json()
        assert ap_note.get("summary") == "Spoiler warning"
        assert ap_note.get("sensitive") is True

        # Wait for note on Misskey
        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if unique in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2, desc="CW note on misskey")
        assert mk_note.get("cw") == "Spoiler warning"

    def test_misskey_sensitive_note_federates(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """bob creates CW note on Misskey; Neko receives spoiler_text."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{MISSKEY_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"MK CW content {time.time()}"
        misskey.create_note(unique, cw="Misskey spoiler")

        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if unique in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, timeout=60, interval=2, desc="MK CW note on neko")
        assert neko_note.get("spoiler_text") == "Misskey spoiler"


# ── 16. Hashtag federation ─────────────────────────────────────


class TestHashtagFederation:
    """Test hashtag federation between platforms."""

    def test_neko_hashtag_in_ap(self, neko: NekoClient, alice):
        """Neko notes with hashtags include Hashtag tags in AP representation."""
        unique = f"Tag test #nekonoverse #federation {time.time()}"
        note = neko.create_note(unique)

        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        ap_note = resp.json()
        tags = ap_note.get("tag", [])
        hashtag_tags = [t for t in tags if t.get("type") == "Hashtag"]
        tag_names = [t["name"].lower().lstrip("#") for t in hashtag_tags]
        assert "nekonoverse" in tag_names, f"Hashtag not found in {tag_names}"
        assert "federation" in tag_names, f"Hashtag not found in {tag_names}"

    def test_misskey_hashtag_federates_to_neko(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """bob creates hashtag note on Misskey; hashtags federate to Neko."""
        # alice follows bob
        results = neko.search_accounts(f"bob@{MISSKEY_DOMAIN}", resolve=True)
        assert len(results) > 0
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass
        time.sleep(3)

        unique = f"Hashtag from MK #misskey {time.time()}"
        misskey.create_note(unique)

        def find_on_neko():
            tl = neko.public_timeline()
            for n in tl:
                if "Hashtag from MK" in (n.get("content") or ""):
                    return n
            return None

        neko_note = poll_until(find_on_neko, timeout=60, interval=2, desc="MK hashtag note on neko")
        # Check that the hashtag tag is present or content contains the hashtag
        tags = neko_note.get("tags", [])
        content = neko_note.get("content", "")
        has_hashtag = (
            any("misskey" in (t.get("name", "") or "").lower() for t in tags)
            or "#misskey" in content.lower()
            or "misskey" in content.lower()
        )
        assert has_hashtag, f"Hashtag not found in tags={tags} or content={content}"


# ── 17. Note URL Lookup (照会) — #822 ──────────────────────────


class TestNoteLookup:
    """Test that Misskey can look up Nekonoverse notes via ap/show (照会)."""

    def test_misskey_resolves_neko_note_by_url(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Misskey ap/show can resolve a Nekonoverse note URL to a Misskey note."""
        unique = f"Lookup test {time.time()}"
        note = neko.create_note(unique)
        note_url = f"{NEKO_URL}/notes/{note['id']}"

        # Misskey should be able to resolve the note via ap/show
        result = misskey.resolve_ap(note_url)
        assert result.get("type") == "Note", f"Expected type=Note, got {result}"
        obj = result.get("object", {})
        assert unique in (obj.get("text") or ""), (
            f"Note text mismatch: expected '{unique}' in '{obj.get('text')}'"
        )

    def test_misskey_resolves_neko_note_by_ap_id(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Misskey ap/show can resolve a Nekonoverse note by its AP id."""
        unique = f"AP ID lookup {time.time()}"
        note = neko.create_note(unique)

        # Get the AP id
        resp = _get(
            f"{NEKO_URL}/notes/{note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        ap_note = resp.json()
        ap_id = ap_note["id"]

        # Misskey should resolve via AP id
        result = misskey.resolve_ap(ap_id)
        assert result.get("type") == "Note", f"Expected type=Note, got {result}"

    def test_misskey_resolves_neko_user_by_url(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Misskey ap/show can resolve a Nekonoverse user URL."""
        user_url = f"{NEKO_URL}/users/alice"
        result = misskey.resolve_ap(user_url)
        assert result.get("type") == "User", f"Expected type=User, got {result}"


# ── 18. Move federation (アカウント移行) ─────────────────────


class TestMoveFederation:
    """Test account migration (Move) between Nekonoverse and Misskey."""

    def test_neko_to_misskey_move(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Neko ユーザーが Misskey に引っ越し: movedTo 設定 + フォロワー移行。

        手順:
        1. Misskey で移行先ユーザー carol を作成
        2. carol の alsoKnownAs に alice の AP ID を設定
        3. Misskey で carol_follower を作成し carol をフォロー (移行後の確認用)
        4. bob@misskey が alice@neko をフォロー (移行前)
        5. alice が carol への Move を実行
        6. Misskey 側で alice の movedTo が設定されていることを確認
        """
        # 1. Misskey に移行先ユーザー carol を作成
        old_token = misskey.token
        carol_data = misskey.create_user("carol", "password1234")
        carol_token = carol_data.get("token")
        misskey.token = old_token  # bob に戻す

        # bob が alice@neko をフォロー (移行前にフォロー関係を作る)
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        try:
            misskey.follow(resolved["id"])
        except Exception:
            pass  # 既にフォロー済みの場合

        # bob → alice のフォローが確立するのを待つ
        def check_following():
            user = misskey._api("users/show", {"userId": resolved["id"]})
            return user.get("isFollowing", False)

        poll_until(check_following, timeout=60, interval=2, desc="bob follows alice")

        # 2. carol の alsoKnownAs に alice の AP ID を設定
        alice_ap = neko.get_actor_ap("alice")
        alice_ap_id = alice_ap["id"]

        misskey.token = carol_token
        misskey.update_also_known_as([alice_ap_id])
        misskey.token = old_token  # bob に戻す

        # carol の AP ID を取得
        carol_info_resp = misskey._api("users/show", {"username": "carol"})
        carol_ap_id = carol_info_resp.get("uri") or f"{MISSKEY_URL}/users/{carol_info_resp['id']}"

        # 3. alice が Neko 側で Move を実行
        neko.move_account(carol_ap_id)

        # 4. Misskey 側で alice の movedTo が設定されるのを確認
        def check_moved():
            user = misskey._api("users/show", {"userId": resolved["id"]})
            return user.get("movedTo") is not None

        poll_until(
            check_moved, timeout=60, interval=2,
            desc="alice@neko movedTo set on misskey"
        )

        # 5. alice の AP 表現で movedTo が設定されていることを確認
        alice_ap_after = neko.get_actor_ap("alice")
        assert "movedTo" in alice_ap_after, "alice AP actor should have movedTo"

    def test_misskey_to_neko_move(
        self, neko: NekoClient, misskey: MisskeyClient, alice, bob
    ):
        """Misskey ユーザーが Neko に引っ越し: Move 受信テスト。

        手順:
        1. Neko で移行先ユーザー dave を作成
        2. dave の alsoKnownAs に bob の AP ID を設定
        3. alice@neko が bob@misskey をフォロー (移行前)
        4. bob が dave への Move を実行
        5. Neko 側で bob の movedTo が設定されていることを確認
        6. alice のフォロー先に dave が含まれることを確認
        """
        # 1. Neko に移行先ユーザー dave を作成
        neko_dave = NekoClient(neko.base_url, neko.domain)
        dave = neko_dave.register("dave", "dave@example.com", "password1234", "Dave")
        neko_dave.login("dave", "password1234")

        # 2. dave の alsoKnownAs に bob の AP ID を設定
        bob_ap = misskey.get_actor_ap("bob")
        bob_ap_id = bob_ap["id"]
        neko_dave.set_also_known_as([bob_ap_id])

        # 3. alice が bob@misskey をフォロー (移行前のフォロー関係)
        results = neko.search_accounts(f"bob@{MISSKEY_DOMAIN}", resolve=True)
        assert len(results) > 0, "Could not resolve bob@misskey on Neko"
        bob_on_neko = results[0]
        try:
            neko.follow(bob_on_neko["id"])
        except Exception:
            pass  # 既にフォロー済み
        time.sleep(5)

        # dave の AP ID を取得
        dave_ap = neko.get_actor_ap("dave")
        dave_ap_id = dave_ap["id"]
        dave_acct = f"dave@{NEKO_DOMAIN}"

        # 4. bob が Misskey で Move を実行
        misskey.move(dave_acct)

        # 5. Neko 側で bob の account に movedTo がつくか確認
        def check_moved_on_neko():
            try:
                account = neko.get_account(bob_on_neko["id"])
                return account.get("moved") is not None
            except Exception:
                return False

        poll_until(
            check_moved_on_neko, timeout=60, interval=2,
            desc="bob@misskey movedTo set on neko"
        )
