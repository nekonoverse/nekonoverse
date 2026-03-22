"""Fixtures and helpers for Mitra cross-platform federation tests."""

import os
import ssl
import time

import httpx
import pytest

NEKO_URL = os.environ.get("NEKO_URL", "https://nekonoverse")
MITRA_URL = os.environ.get("MITRA_URL", "https://mitra")
NEKO_DOMAIN = os.environ.get("NEKO_DOMAIN", "nekonoverse")
MITRA_DOMAIN = os.environ.get("MITRA_DOMAIN", "mitra")

# Accept self-signed certs in test environment
SSL_CONTEXT = ssl.create_default_context()
SSL_CONTEXT.check_hostname = False
SSL_CONTEXT.verify_mode = ssl.CERT_NONE


def wait_for_health(url: str, path: str, timeout: int = 120, method: str = "GET"):
    """Poll until instance is ready."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if method == "POST":
                resp = httpx.post(f"{url}{path}", json={}, timeout=5, verify=False)
            else:
                resp = httpx.get(f"{url}{path}", timeout=5, verify=False)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(2)
    raise TimeoutError(f"{url} did not become healthy within {timeout}s")


def poll_until(predicate, *, timeout: int = 30, interval: float = 1.0, desc: str = ""):
    """Poll until predicate returns truthy."""
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
    msg = f"Timed out: {desc}" if desc else "Poll timed out"
    if last_exc:
        msg += f" (last: {last_exc})"
    raise TimeoutError(msg)


class NekoClient:
    """Helper to interact with Nekonoverse instance."""

    def __init__(self, base_url: str, domain: str):
        self.base_url = base_url
        self.domain = domain
        self.http = httpx.Client(base_url=base_url, timeout=15, verify=False)

    def health(self) -> dict:
        return self.http.get("/api/v1/health").json()

    def register(self, username: str, email: str, password: str, display_name: str | None = None):
        body = {"username": username, "email": email, "password": password}
        if display_name:
            body["display_name"] = display_name
        resp = self.http.post("/api/v1/accounts", json=body)
        resp.raise_for_status()
        return resp.json()

    def login(self, username: str, password: str):
        resp = self.http.post(
            "/api/v1/auth/login", json={"username": username, "password": password}
        )
        resp.raise_for_status()
        return resp.json()

    def create_note(self, content: str, visibility: str = "public", **kwargs):
        body = {"content": content, "visibility": visibility, **kwargs}
        resp = self.http.post("/api/v1/statuses", json=body)
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

    def home_timeline(self, limit: int = 20):
        resp = self.http.get("/api/v1/timelines/home", params={"limit": str(limit)})
        resp.raise_for_status()
        return resp.json()

    def search_accounts(self, q: str, resolve: bool = False):
        params = {"q": q}
        if resolve:
            params["resolve"] = "true"
        resp = self.http.get("/api/v1/accounts/search", params=params)
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

    def notifications(self, limit: int = 20):
        resp = self.http.get("/api/v1/notifications", params={"limit": str(limit)})
        resp.raise_for_status()
        return resp.json()

    def webfinger(self, acct: str):
        resp = self.http.get("/.well-known/webfinger", params={"resource": f"acct:{acct}"})
        resp.raise_for_status()
        return resp.json()

    def get_actor_ap(self, username: str):
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


class MitraClient:
    """Helper to interact with Mitra instance via Mastodon-compatible API."""

    def __init__(self, base_url: str, domain: str):
        self.base_url = base_url
        self.domain = domain
        self.http = httpx.Client(base_url=base_url, timeout=15, verify=False)
        self.token: str | None = None

    def health(self) -> bool:
        try:
            resp = self.http.get("/api/v1/instance")
            return resp.status_code == 200
        except Exception:
            return False

    def _create_app(self) -> dict:
        """Create an OAuth app for registration/login."""
        resp = self.http.post("/api/v1/apps", json={
            "client_name": "federation-test",
            "redirect_uris": "urn:ietf:wg:oauth:2.0:oob",
            "scopes": "read write follow",
        })
        resp.raise_for_status()
        return resp.json()

    def login(self, username: str, password: str):
        """Login via OAuth password grant."""
        app = self._create_app()
        resp = self.http.post("/oauth/token", data={
            "client_id": app["client_id"],
            "client_secret": app["client_secret"],
            "grant_type": "password",
            "username": username,
            "password": password,
            "scope": "read write follow",
        })
        resp.raise_for_status()
        data = resp.json()
        self.token = data["access_token"]
        return data

    def _headers(self) -> dict:
        h = {}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def verify_credentials(self) -> dict:
        resp = self.http.get("/api/v1/accounts/verify_credentials", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def create_status(self, content: str, visibility: str = "public"):
        resp = self.http.post("/api/v1/statuses", json={
            "status": content,
            "visibility": visibility,
        }, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def get_status(self, status_id: str):
        resp = self.http.get(f"/api/v1/statuses/{status_id}", headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def timeline_local(self, limit: int = 20):
        resp = self.http.get(
            "/api/v1/timelines/public",
            params={"local": "true", "limit": str(limit)},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def timeline_home(self, limit: int = 20):
        resp = self.http.get(
            "/api/v1/timelines/home",
            params={"limit": str(limit)},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def search_accounts(self, q: str, resolve: bool = False):
        params = {"q": q, "resolve": "true" if resolve else "false"}
        resp = self.http.get("/api/v1/accounts/search", params=params, headers=self._headers())
        resp.raise_for_status()
        return resp.json()

    def follow(self, account_id: str):
        resp = self.http.post(
            f"/api/v1/accounts/{account_id}/follow", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def unfollow(self, account_id: str):
        resp = self.http.post(
            f"/api/v1/accounts/{account_id}/unfollow", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_relationships(self, ids: list[str]):
        params = [("id[]", id_) for id_ in ids]
        resp = self.http.get(
            "/api/v1/accounts/relationships", params=params, headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def get_notifications(self, limit: int = 20):
        resp = self.http.get(
            "/api/v1/notifications",
            params={"limit": str(limit)},
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()

    def favourite(self, status_id: str):
        resp = self.http.post(
            f"/api/v1/statuses/{status_id}/favourite", headers=self._headers()
        )
        resp.raise_for_status()
        return resp.json()

    def webfinger(self, acct: str):
        resp = self.http.get(
            "/.well-known/webfinger", params={"resource": f"acct:{acct}"}
        )
        resp.raise_for_status()
        return resp.json()

    def get_actor_ap(self, actor_url: str):
        resp = httpx.get(
            actor_url,
            headers={"Accept": "application/activity+json"},
            timeout=15,
            verify=False,
        )
        resp.raise_for_status()
        return resp.json()


@pytest.fixture(scope="session", autouse=True)
def wait_for_instances():
    """Wait for both instances to be healthy."""
    wait_for_health(NEKO_URL, "/api/v1/health")
    wait_for_health(MITRA_URL, "/api/v1/instance")


@pytest.fixture(scope="session")
def neko() -> NekoClient:
    return NekoClient(NEKO_URL, NEKO_DOMAIN)


@pytest.fixture(scope="session")
def mitra() -> MitraClient:
    return MitraClient(MITRA_URL, MITRA_DOMAIN)


@pytest.fixture(scope="session")
def alice(neko: NekoClient) -> dict:
    """Register alice on Nekonoverse (idempotent)."""
    try:
        user = neko.register("alice", "alice@example.com", "password1234", "Alice")
    except httpx.HTTPStatusError:
        user = {"username": "alice"}
    neko.login("alice", "password1234")
    return user


@pytest.fixture(scope="session")
def bob(mitra: MitraClient) -> dict:
    """Login as bob on Mitra (created by entrypoint via mitractl)."""
    data = mitra.login("bob", "password123")
    return data
