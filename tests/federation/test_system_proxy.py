"""Federation tests for the system.proxy account.

Verifies that the system.proxy actor is properly exposed to the fediverse
and behaves correctly in cross-instance scenarios.
"""

import httpx

from conftest import (
    INSTANCE_A,
    INSTANCE_A_DOMAIN,
    INSTANCE_B,
    INSTANCE_B_DOMAIN,
    InstanceClient,
)


# -- system.proxy AP actor --


class TestSystemProxyActor:
    """Verify system.proxy is a valid AP actor on both instances."""

    def test_proxy_actor_exists_on_instance_a(self, instance_a: InstanceClient, alice):
        """system.proxy is accessible via AP endpoint on instance-a."""
        actor = instance_a.get_actor_ap("system.proxy")
        assert actor["type"] == "Application"
        assert actor["preferredUsername"] == "system.proxy"
        assert actor["id"] == f"http://{INSTANCE_A_DOMAIN}/users/system.proxy"

    def test_proxy_actor_exists_on_instance_b(self, instance_b: InstanceClient, bob):
        """system.proxy is accessible via AP endpoint on instance-b."""
        actor = instance_b.get_actor_ap("system.proxy")
        assert actor["type"] == "Application"
        assert actor["preferredUsername"] == "system.proxy"
        assert actor["id"] == f"http://{INSTANCE_B_DOMAIN}/users/system.proxy"

    def test_proxy_actor_is_bot(self, instance_a: InstanceClient, alice):
        """system.proxy actor type is Service/Application (bot)."""
        actor = instance_a.get_actor_ap("system.proxy")
        # ActivityPub Application type indicates a bot/service account
        assert actor["type"] == "Application"

    def test_proxy_actor_has_public_key(self, instance_a: InstanceClient, alice):
        """system.proxy has a valid public key for HTTP Signature verification."""
        actor = instance_a.get_actor_ap("system.proxy")
        assert "publicKey" in actor
        pk = actor["publicKey"]
        assert pk["id"] == f"http://{INSTANCE_A_DOMAIN}/users/system.proxy#main-key"
        assert pk["owner"] == f"http://{INSTANCE_A_DOMAIN}/users/system.proxy"
        assert "-----BEGIN PUBLIC KEY-----" in pk["publicKeyPem"]
        assert "-----END PUBLIC KEY-----" in pk["publicKeyPem"]

    def test_proxy_actor_has_inbox_outbox(self, instance_a: InstanceClient, alice):
        """system.proxy has inbox/outbox endpoints for AP delivery."""
        actor = instance_a.get_actor_ap("system.proxy")
        assert actor["inbox"] == f"http://{INSTANCE_A_DOMAIN}/users/system.proxy/inbox"
        assert actor["outbox"] == f"http://{INSTANCE_A_DOMAIN}/users/system.proxy/outbox"

    def test_proxy_actor_has_shared_inbox(self, instance_a: InstanceClient, alice):
        """system.proxy has shared inbox endpoint."""
        actor = instance_a.get_actor_ap("system.proxy")
        endpoints = actor.get("endpoints", {})
        assert endpoints.get("sharedInbox") == f"http://{INSTANCE_A_DOMAIN}/inbox"

    def test_proxy_actor_not_discoverable(self, instance_a: InstanceClient, alice):
        """system.proxy should not be discoverable (hidden from directory)."""
        actor = instance_a.get_actor_ap("system.proxy")
        assert actor.get("discoverable") is False


# -- Cross-instance fetch --


class TestSystemProxyCrossInstance:
    """Verify system.proxy can be fetched cross-instance (required for follow delivery)."""

    def test_fetch_proxy_actor_from_remote(self, alice, bob):
        """instance-b can fetch system.proxy from instance-a via AP."""
        resp = httpx.get(
            f"{INSTANCE_A}/users/system.proxy",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        actor = resp.json()
        assert actor["type"] == "Application"
        assert actor["preferredUsername"] == "system.proxy"

    def test_fetch_proxy_actor_reverse_direction(self, alice, bob):
        """instance-a can fetch system.proxy from instance-b via AP."""
        resp = httpx.get(
            f"{INSTANCE_B}/users/system.proxy",
            headers={"Accept": "application/activity+json"},
            timeout=10,
        )
        assert resp.status_code == 200
        actor = resp.json()
        assert actor["type"] == "Application"
        assert actor["preferredUsername"] == "system.proxy"


# -- WebFinger --


class TestSystemProxyWebFinger:
    """Verify system.proxy is resolvable via WebFinger."""

    def test_webfinger_proxy_on_instance_a(self, instance_a: InstanceClient, alice):
        result = instance_a.webfinger(f"system.proxy@{INSTANCE_A_DOMAIN}")
        assert result["subject"] == f"acct:system.proxy@{INSTANCE_A_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links
        assert links["self"]["href"] == f"http://{INSTANCE_A_DOMAIN}/users/system.proxy"

    def test_webfinger_proxy_on_instance_b(self, instance_b: InstanceClient, bob):
        result = instance_b.webfinger(f"system.proxy@{INSTANCE_B_DOMAIN}")
        assert result["subject"] == f"acct:system.proxy@{INSTANCE_B_DOMAIN}"
        links = {link["rel"]: link for link in result["links"]}
        assert "self" in links
        assert links["self"]["href"] == f"http://{INSTANCE_B_DOMAIN}/users/system.proxy"

    def test_webfinger_cross_instance(self, alice, bob):
        """Cross-instance WebFinger resolution for system.proxy."""
        resp = httpx.get(
            f"{INSTANCE_A}/.well-known/webfinger",
            params={"resource": f"acct:system.proxy@{INSTANCE_A_DOMAIN}"},
            timeout=10,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["subject"] == f"acct:system.proxy@{INSTANCE_A_DOMAIN}"


# -- Authentication rejection --


class TestSystemProxyAuthRejection:
    """Verify system.proxy cannot be used for login."""

    def test_proxy_login_rejected(self, instance_a: InstanceClient, alice):
        """system.proxy cannot authenticate via password login."""
        resp = instance_a.http.post(
            "/api/v1/auth/login",
            json={"username": "system.proxy", "password": "any-password"},
        )
        # Login should fail (401 or 403)
        assert resp.status_code in (401, 403)

    def test_proxy_login_rejected_on_instance_b(self, instance_b: InstanceClient, bob):
        """system.proxy cannot authenticate on instance-b either."""
        resp = instance_b.http.post(
            "/api/v1/auth/login",
            json={"username": "system.proxy", "password": "any-password"},
        )
        assert resp.status_code in (401, 403)


# -- Followers/Following collections --


class TestSystemProxyCollections:
    """Verify system.proxy has proper AP collections."""

    def test_proxy_followers_collection(self, instance_a: InstanceClient, alice):
        """system.proxy has an initially empty followers collection."""
        followers = instance_a.get_followers("system.proxy")
        assert followers["type"] == "OrderedCollection"
        assert followers["totalItems"] == 0

    def test_proxy_following_collection(self, instance_a: InstanceClient, alice):
        """system.proxy has an initially empty following collection."""
        following = instance_a.get_following("system.proxy")
        assert following["type"] == "OrderedCollection"
        assert following["totalItems"] == 0

    def test_proxy_outbox_empty(self, instance_a: InstanceClient, alice):
        """system.proxy has an empty outbox (it doesn't post)."""
        resp = instance_a.http.get(
            "/users/system.proxy/outbox",
            headers={"Accept": "application/activity+json"},
        )
        assert resp.status_code == 200
        outbox = resp.json()
        assert outbox["type"] == "OrderedCollection"
        assert outbox["totalItems"] == 0
