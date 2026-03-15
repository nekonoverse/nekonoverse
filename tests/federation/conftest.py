"""Fixtures and helpers for federation e2e tests."""

import os
import time

import httpx
import pytest

INSTANCE_A = os.environ.get("INSTANCE_A_URL", "http://instance-a")
INSTANCE_B = os.environ.get("INSTANCE_B_URL", "http://instance-b")
INSTANCE_A_DOMAIN = os.environ.get("INSTANCE_A_DOMAIN", "instance-a")
INSTANCE_B_DOMAIN = os.environ.get("INSTANCE_B_DOMAIN", "instance-b")


def wait_for_instance(url: str, timeout: int = 60):
    """Poll health endpoint until the instance is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = httpx.get(f"{url}/api/v1/health", timeout=5)
            if resp.status_code == 200:
                return
        except httpx.ConnectError:
            pass
        time.sleep(1)
    raise TimeoutError(f"Instance {url} did not become healthy within {timeout}s")


def poll_until(predicate, *, timeout: int = 30, interval: float = 0.5, desc: str = ""):
    """Poll a predicate function until it returns a truthy value."""
    deadline = time.time() + timeout
    last_exc = None
    while time.time() < deadline:
        try:
            result = predicate()
            if result:
                return result
        except Exception as exc:
            last_exc = exc
        time.sleep(interval)
    msg = f"Timed out waiting for: {desc}" if desc else "Poll timed out"
    if last_exc:
        msg += f" (last error: {last_exc})"
    raise TimeoutError(msg)


class InstanceClient:
    """Helper to interact with a nekonoverse instance."""

    def __init__(self, base_url: str, domain: str):
        self.base_url = base_url
        self.domain = domain
        self.http = httpx.Client(base_url=base_url, timeout=15)

    def health(self) -> dict:
        return self.http.get("/api/v1/health").json()

    def register(self, username: str, email: str, password: str, display_name: str | None = None):
        body = {"username": username, "email": email, "password": password}
        if display_name:
            body["display_name"] = display_name
        resp = self.http.post("/api/v1/accounts", json=body)
        if resp.status_code != 201:
            print(f"Registration failed: {resp.status_code} {resp.text}")
        resp.raise_for_status()
        return resp.json()

    def login(self, username: str, password: str):
        resp = self.http.post("/api/v1/auth/login", json={"username": username, "password": password})
        resp.raise_for_status()
        # Session cookie is stored in the client automatically
        return resp.json()

    def verify_credentials(self):
        resp = self.http.get("/api/v1/accounts/verify_credentials")
        resp.raise_for_status()
        return resp.json()

    def create_note(self, content: str, visibility: str = "public"):
        resp = self.http.post(
            "/api/v1/statuses", json={"content": content, "visibility": visibility}
        )
        resp.raise_for_status()
        return resp.json()

    def get_note(self, note_id: str):
        resp = self.http.get(f"/api/v1/statuses/{note_id}")
        resp.raise_for_status()
        return resp.json()

    def public_timeline(self, local: bool = False):
        params = {}
        if local:
            params["local"] = "true"
        resp = self.http.get("/api/v1/timelines/public", params=params)
        resp.raise_for_status()
        return resp.json()

    def follow(self, actor_id: str):
        resp = self.http.post(f"/api/v1/accounts/{actor_id}/follow")
        resp.raise_for_status()
        return resp.json()

    def unfollow(self, actor_id: str):
        resp = self.http.post(f"/api/v1/accounts/{actor_id}/unfollow")
        resp.raise_for_status()
        return resp.json()

    def react(self, note_id: str, emoji: str):
        resp = self.http.post(f"/api/v1/statuses/{note_id}/react/{emoji}")
        resp.raise_for_status()
        return resp.json()

    def unreact(self, note_id: str, emoji: str):
        resp = self.http.post(f"/api/v1/statuses/{note_id}/unreact/{emoji}")
        resp.raise_for_status()
        return resp.json()

    def webfinger(self, acct: str):
        resp = self.http.get("/.well-known/webfinger", params={"resource": f"acct:{acct}"})
        resp.raise_for_status()
        return resp.json()

    def lookup_account(self, acct: str):
        resp = self.http.get("/api/v1/accounts/lookup", params={"acct": acct})
        resp.raise_for_status()
        return resp.json()

    def get_actor_ap(self, username: str):
        """Fetch ActivityPub actor JSON."""
        resp = self.http.get(
            f"/users/{username}",
            headers={"Accept": "application/activity+json"},
        )
        resp.raise_for_status()
        return resp.json()

    def get_followers(self, username: str):
        resp = self.http.get(
            f"/users/{username}/followers",
            headers={"Accept": "application/activity+json"},
        )
        resp.raise_for_status()
        return resp.json()

    def get_following(self, username: str):
        resp = self.http.get(
            f"/users/{username}/following",
            headers={"Accept": "application/activity+json"},
        )
        resp.raise_for_status()
        return resp.json()

    def search_accounts(self, q: str, resolve: bool = False):
        """Search/resolve accounts (triggers WebFinger for remote)."""
        resp = self.http.get(
            "/api/v2/search",
            params={"q": q, "type": "accounts", "resolve": str(resolve).lower()},
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("accounts", [])

    def update_credentials(self, **kwargs):
        """Update account credentials (display_name, also_known_as, etc.)."""
        import json as _json

        form_data = {}
        for key, value in kwargs.items():
            if isinstance(value, (list, dict)):
                form_data[key] = _json.dumps(value)
            elif value is not None:
                form_data[key] = value
        resp = self.http.patch(
            "/api/v1/accounts/update_credentials",
            data=form_data,
        )
        resp.raise_for_status()
        return resp.json()

    def move_account(self, target_ap_id: str):
        """Initiate account migration to target."""
        resp = self.http.post(
            "/api/v1/accounts/move",
            json={"target_ap_id": target_ap_id},
        )
        resp.raise_for_status()
        return resp.json()

    def get_account(self, actor_id: str):
        """Get account info by actor UUID."""
        resp = self.http.get(f"/api/v1/accounts/{actor_id}")
        resp.raise_for_status()
        return resp.json()


@pytest.fixture(scope="session", autouse=True)
def wait_for_instances():
    """Wait for both instances to be healthy before running tests."""
    wait_for_instance(INSTANCE_A)
    wait_for_instance(INSTANCE_B)


@pytest.fixture(scope="session")
def instance_a() -> InstanceClient:
    return InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)


@pytest.fixture(scope="session")
def instance_b() -> InstanceClient:
    return InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)


@pytest.fixture(scope="session")
def alice(instance_a: InstanceClient) -> dict:
    """Register and login alice on instance A."""
    user = instance_a.register("alice", "alice@example.com", "password1234", "Alice")
    instance_a.login("alice", "password1234")
    return user


@pytest.fixture(scope="session")
def bob(instance_b: InstanceClient) -> dict:
    """Register and login bob on instance B."""
    user = instance_b.register("bob", "bob@example.com", "password1234", "Bob")
    instance_b.login("bob", "password1234")
    return user
