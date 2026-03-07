"""Cross-platform federation tests: Nekonoverse <-> Misskey.

Tests protocol-level compatibility between Nekonoverse and Misskey.
Full federation flow (follow, note delivery, reactions) requires HTTPS,
which Misskey mandates for remote user resolution.
"""

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

# Misskey always uses HTTPS for remote user resolution (WebFinger, actor fetch).
# Full federation tests require HTTPS termination with valid certs.
REQUIRES_HTTPS = pytest.mark.skip(
    reason="Misskey requires HTTPS for remote user resolution"
)


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
        assert links["self"]["href"] == f"http://{NEKO_DOMAIN}/users/alice"

    def test_misskey_webfinger(self, misskey: MisskeyClient, bob):
        result = misskey.webfinger(f"bob@{MISSKEY_DOMAIN}")
        assert result["subject"] == f"acct:bob@{MISSKEY_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links

    def test_cross_webfinger_neko_from_misskey(self, alice):
        """Misskey network can reach Nekonoverse WebFinger."""
        resp = httpx.get(
            f"{NEKO_URL}/.well-known/webfinger",
            params={"resource": f"acct:alice@{NEKO_DOMAIN}"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["subject"] == f"acct:alice@{NEKO_DOMAIN}"

    def test_cross_webfinger_misskey_from_neko(self, bob):
        """Nekonoverse network can reach Misskey WebFinger."""
        resp = httpx.get(
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
        assert actor["id"] == f"http://{NEKO_DOMAIN}/users/alice"
        assert "publicKey" in actor

    def test_misskey_actor(self, misskey: MisskeyClient, bob):
        actor = misskey.get_actor_ap("bob")
        assert actor["type"] == "Person"
        assert actor["preferredUsername"] == "bob"
        assert "publicKey" in actor

    def test_cross_actor_fetch(self, alice, bob):
        """Each instance can fetch the other's actor via AP."""
        resp = httpx.get(
            f"{NEKO_URL}/users/alice",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["preferredUsername"] == "alice"

        # Misskey actor fetch (via WebFinger self link)
        mk_wf = httpx.get(
            f"{MISSKEY_URL}/.well-known/webfinger",
            params={"resource": f"acct:bob@{MISSKEY_DOMAIN}"},
            timeout=10,
        ).json()
        self_link = next(l["href"] for l in mk_wf["links"] if l.get("rel") == "self")
        resp2 = httpx.get(self_link, headers={"Accept": "application/activity+json"}, timeout=10)
        assert resp2.status_code == 200
        assert resp2.json()["preferredUsername"] == "bob"

    def test_neko_actor_has_misskey_extensions(self, neko: NekoClient, alice):
        """Nekonoverse actor includes Misskey-compatible extensions."""
        actor = neko.get_actor_ap("alice")
        # Check for isCat field (Misskey extension)
        assert "isCat" in actor
        # Check for shared inbox
        assert "endpoints" in actor
        assert "sharedInbox" in actor["endpoints"]

    def test_actor_public_key_format(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """Both actors have properly formatted public keys for HTTP Signatures."""
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
        note = neko.create_note("Hello from Nekonoverse! 🐱")
        assert "id" in note
        assert note["content"] is not None

    def test_misskey_create_note(self, misskey: MisskeyClient, bob):
        result = misskey.create_note("Hello from Misskey! 📝")
        assert "createdNote" in result
        assert result["createdNote"]["text"] == "Hello from Misskey! 📝"

    def test_neko_local_timeline(self, neko: NekoClient, alice):
        tl = neko.public_timeline(local=True)
        assert len(tl) >= 1
        assert any("Nekonoverse" in (n.get("content") or "") for n in tl)

    def test_misskey_local_timeline(self, misskey: MisskeyClient, bob):
        tl = misskey.timeline_local()
        assert len(tl) >= 1
        assert any(n.get("text", "").startswith("Hello from Misskey") for n in tl)


# ── 5. AP cross-fetch (protocol compatibility) ──────────────


class TestAPCrossFetch:
    def test_neko_note_fetchable_via_ap(self, neko: NekoClient, alice):
        """Nekonoverse notes are fetchable via AP from any network peer."""
        note = neko.create_note("Fetchable note!")
        note_id = note["id"]

        resp = httpx.get(
            f"{NEKO_URL}/notes/{note_id}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Note"
        assert data["attributedTo"] == f"http://{NEKO_DOMAIN}/users/alice"

    def test_misskey_note_fetchable_via_ap(self, misskey: MisskeyClient, bob):
        """Misskey notes are fetchable via AP from any network peer."""
        result = misskey.create_note("Fetchable Misskey note!")
        mk_note = result["createdNote"]

        resp = httpx.get(
            f"{MISSKEY_URL}/notes/{mk_note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Note"

    def test_neko_note_ap_format_compatible(self, neko: NekoClient, alice):
        """Nekonoverse note AP format is compatible with Misskey expectations."""
        note = neko.create_note("Check my AP format!")
        note_id = note["id"]

        resp = httpx.get(
            f"{NEKO_URL}/notes/{note_id}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        data = resp.json()

        # Required fields for Misskey compatibility
        assert "@context" in data
        assert data["type"] == "Note"
        assert "id" in data
        assert "attributedTo" in data
        assert "content" in data
        assert "published" in data
        assert "to" in data

    def test_neko_outbox_format(self, neko: NekoClient, alice):
        """Nekonoverse outbox format is compatible."""
        resp = httpx.get(
            f"{NEKO_URL}/users/alice/outbox",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        outbox = resp.json()
        assert outbox["type"] == "OrderedCollection"
        assert "totalItems" in outbox

    def test_neko_outbox_page(self, neko: NekoClient, alice):
        """Nekonoverse outbox pages contain Create activities."""
        resp = httpx.get(
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
        resp = httpx.get(f"{NEKO_URL}/.well-known/nodeinfo", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["links"]) > 0

        resp2 = httpx.get(f"{NEKO_URL}/nodeinfo/2.0", timeout=10)
        assert resp2.status_code == 200
        ni = resp2.json()
        assert ni["software"]["name"] == "nekonoverse"

    def test_misskey_nodeinfo(self, misskey: MisskeyClient, bob):
        resp = httpx.get(f"{MISSKEY_URL}/.well-known/nodeinfo", timeout=10)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["links"]) > 0

        # Fetch actual nodeinfo
        nodeinfo_href = data["links"][0]["href"]
        # Replace hostname with MISSKEY_URL since href uses the configured domain
        path = "/" + nodeinfo_href.split("/", 3)[-1]
        resp2 = httpx.get(f"{MISSKEY_URL}{path}", timeout=10)
        assert resp2.status_code == 200
        ni = resp2.json()
        assert ni["software"]["name"] == "misskey"


# ── 7. Poll AP format ───────────────────────────────────────


class TestPoll:
    def test_misskey_creates_poll(self, misskey: MisskeyClient, bob):
        """bob@misskey creates a poll note."""
        result = misskey.create_poll_note(
            "Which platform?",
            choices=["Nekonoverse", "Misskey", "Both"],
        )
        assert "createdNote" in result
        assert result["createdNote"]["poll"] is not None

    def test_misskey_poll_ap_format(self, misskey: MisskeyClient, bob):
        """Misskey poll note uses Question type in AP."""
        result = misskey.create_poll_note(
            "Best cat emoji?",
            choices=["🐱", "😺", "🐈"],
        )
        mk_note = result["createdNote"]

        resp = httpx.get(
            f"{MISSKEY_URL}/notes/{mk_note['id']}",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "Question"
        assert "oneOf" in data or "anyOf" in data


# ── 8. Full federation (requires HTTPS) ─────────────────────
# These tests require Misskey to resolve remote users via HTTPS.
# They are skipped in HTTP-only test environments.


class TestFullFederation:
    @REQUIRES_HTTPS
    def test_misskey_resolves_neko_user(self, misskey: MisskeyClient, alice, bob):
        """Misskey resolves alice@nekonoverse via WebFinger+actor fetch."""
        result = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        assert result["username"] == "alice"

    @REQUIRES_HTTPS
    def test_misskey_follows_neko_user(self, misskey: MisskeyClient, alice, bob):
        """bob@misskey follows alice@nekonoverse."""
        resolved = misskey.search_user_by_username("alice", host=NEKO_DOMAIN)
        misskey.follow(resolved["id"])

        def check_following():
            user = misskey._api("users/show", {"userId": resolved["id"]})
            return user.get("isFollowing", False)

        poll_until(check_following, timeout=30, desc="bob follows alice")

    @REQUIRES_HTTPS
    def test_neko_note_appears_on_misskey(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """After follow, alice's notes appear on Misskey's timeline."""
        neko.create_note("Federation test note from Nekonoverse! 🌐")

        def check_note_federated():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            return any("Federation test note" in (n.get("text") or "") for n in tl)

        poll_until(check_note_federated, timeout=60, interval=2, desc="neko note on misskey")

    @REQUIRES_HTTPS
    def test_misskey_reacts_to_federated_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """bob reacts to a federated note; reaction appears on Nekonoverse."""
        note = neko.create_note("React to this! ❤️")

        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if "React to this" in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2)
        misskey.react(mk_note["id"], "👍")

        def check_reaction():
            n = neko.get_note(note["id"])
            return n.get("reactions_count", 0) > 0

        poll_until(check_reaction, timeout=30, desc="reaction federated to neko")

    @REQUIRES_HTTPS
    def test_misskey_renotes_federated_note(self, neko: NekoClient, misskey: MisskeyClient, alice, bob):
        """bob renotes a federated note from alice."""
        note = neko.create_note("Renote this! 🔄")

        def find_note():
            tl = misskey._api("notes/global-timeline", {"limit": 20})
            for n in tl:
                if "Renote this" in (n.get("text") or ""):
                    return n
            return None

        mk_note = poll_until(find_note, timeout=60, interval=2)
        misskey.renote(mk_note["id"])

        tl = misskey.timeline_local(limit=10)
        assert any(n.get("renoteId") == mk_note["id"] for n in tl)
