"""Cross-platform federation tests: Nekonoverse <-> Misskey.

Uses self-signed certificates for HTTPS to enable full federation.
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

        poll_until(check_following, timeout=30, desc="bob follows alice")

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

        poll_until(check_followers, timeout=30, desc="alice has followers")

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

        poll_until(check_reaction, timeout=30, desc="reaction federated to neko")

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
