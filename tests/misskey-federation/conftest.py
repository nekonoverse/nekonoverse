"""Fixtures and helpers for Misskey cross-platform federation tests."""

import os
import ssl
import time

import httpx
import pytest

NEKO_URL = os.environ.get("NEKO_URL", "https://nekonoverse")
MISSKEY_URL = os.environ.get("MISSKEY_URL", "https://misskey")
NEKO_DOMAIN = os.environ.get("NEKO_DOMAIN", "nekonoverse")
MISSKEY_DOMAIN = os.environ.get("MISSKEY_DOMAIN", "misskey")

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
        resp = self.http.post("/api/v1/auth/login", json={"username": username, "password": password})
        resp.raise_for_status()
        return resp.json()

    def create_note(self, content: str, visibility: str = "public",
                    spoiler_text: str | None = None, **kwargs):
        body = {"content": content, "visibility": visibility, **kwargs}
        if spoiler_text:
            body["spoiler_text"] = spoiler_text
        resp = self.http.post("/api/v1/statuses", json=body)
        resp.raise_for_status()
        return resp.json()

    def delete_note(self, note_id: str):
        resp = self.http.delete(f"/api/v1/statuses/{note_id}")
        resp.raise_for_status()

    def get_note(self, note_id: str):
        resp = self.http.get(f"/api/v1/statuses/{note_id}")
        resp.raise_for_status()
        return resp.json()

    def get_context(self, note_id: str):
        resp = self.http.get(f"/api/v1/statuses/{note_id}/context")
        resp.raise_for_status()
        return resp.json()

    def public_timeline(self, local: bool = False):
        params = {}
        if local:
            params["local"] = "true"
        resp = self.http.get("/api/v1/timelines/public", params=params)
        resp.raise_for_status()
        return resp.json()

    def lookup_account(self, acct: str):
        resp = self.http.get("/api/v1/accounts/lookup", params={"acct": acct})
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

    def react(self, note_id: str, emoji: str):
        resp = self.http.post(f"/api/v1/statuses/{note_id}/react/{emoji}")
        resp.raise_for_status()
        return resp.json()

    def unreact(self, note_id: str, emoji: str):
        resp = self.http.post(f"/api/v1/statuses/{note_id}/unreact/{emoji}")
        resp.raise_for_status()
        return resp.json()

    def reblog(self, note_id: str):
        resp = self.http.post(f"/api/v1/statuses/{note_id}/reblog")
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

    def set_also_known_as(self, ap_ids: list[str]):
        """alsoKnownAs を設定する。"""
        import json
        formdata = {"also_known_as": json.dumps(ap_ids)}
        resp = self.http.patch(
            "/api/v1/accounts/update_credentials",
            data=formdata,
        )
        resp.raise_for_status()
        return resp.json()

    def move_account(self, target_ap_id: str):
        """アカウント移行を開始する。"""
        resp = self.http.post(
            "/api/v1/accounts/move",
            json={"target_ap_id": target_ap_id},
        )
        resp.raise_for_status()
        return resp.json()

    def get_account(self, actor_id: str):
        """アカウント情報を取得する。"""
        resp = self.http.get(f"/api/v1/accounts/{actor_id}")
        resp.raise_for_status()
        return resp.json()


class MisskeyClient:
    """Helper to interact with Misskey instance."""

    def __init__(self, base_url: str, domain: str):
        self.base_url = base_url
        self.domain = domain
        self.http = httpx.Client(base_url=base_url, timeout=15, verify=False)
        self.token: str | None = None

    def health(self) -> bool:
        try:
            resp = self.http.post("/api/ping", json={})
            return resp.status_code == 200
        except Exception:
            return False

    def create_admin(self, username: str, password: str):
        """Create the first admin user (works only when no users exist)."""
        resp = self.http.post("/api/admin/accounts/create", json={
            "username": username,
            "password": password,
        })
        resp.raise_for_status()
        data = resp.json()
        self.token = data.get("token")
        return data

    def _api(self, endpoint: str, body: dict | None = None):
        """Call a Misskey API endpoint with auth."""
        payload = body or {}
        if self.token:
            payload["i"] = self.token
        resp = self.http.post(f"/api/{endpoint}", json=payload)
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    def create_note(self, text: str, visibility: str = "public", **kwargs):
        return self._api("notes/create", {"text": text, "visibility": visibility, **kwargs})

    def get_note(self, note_id: str):
        return self._api("notes/show", {"noteId": note_id})

    def delete_note(self, note_id: str):
        self._api("notes/delete", {"noteId": note_id})

    def get_notifications(self, limit: int = 20):
        return self._api("i/notifications", {"limit": limit})

    def timeline_local(self, limit: int = 20):
        return self._api("notes/local-timeline", {"limit": limit})

    def follow(self, user_id: str):
        return self._api("following/create", {"userId": user_id})

    def react(self, note_id: str, reaction: str):
        return self._api("notes/reactions/create", {"noteId": note_id, "reaction": reaction})

    def unreact(self, note_id: str):
        return self._api("notes/reactions/delete", {"noteId": note_id})

    def get_reactions(self, note_id: str):
        return self._api("notes/reactions", {"noteId": note_id})

    def renote(self, note_id: str):
        return self._api("notes/create", {"renoteId": note_id})

    def quote(self, note_id: str, text: str):
        return self._api("notes/create", {"renoteId": note_id, "text": text})

    def search_user_by_username(self, username: str, host: str | None = None):
        body: dict = {"username": username, "detail": True}
        if host:
            body["host"] = host
        return self._api("users/show", body)

    def resolve_ap(self, uri: str):
        """Resolve an ActivityPub URI to a Misskey object."""
        return self._api("ap/show", {"uri": uri})

    def webfinger(self, acct: str):
        resp = self.http.get("/.well-known/webfinger", params={"resource": f"acct:{acct}"})
        resp.raise_for_status()
        return resp.json()

    def get_actor_ap(self, username: str):
        resp = self.http.get(
            f"/users/{username}",
            headers={"Accept": "application/activity+json"},
        )
        # Misskey uses user IDs in AP URLs, not usernames - try alternate
        if resp.status_code != 200:
            # Look up user first to get ID
            user = self._api("users/show", {"username": username})
            resp = self.http.get(
                f"/users/{user['id']}",
                headers={"Accept": "application/activity+json"},
            )
        resp.raise_for_status()
        return resp.json()

    def create_poll_note(self, text: str, choices: list[str], multiple: bool = False):
        return self._api("notes/create", {
            "text": text,
            "poll": {"choices": choices, "multiple": multiple},
        })

    def create_user(self, username: str, password: str):
        """管理者として新しいユーザーを作成する。"""
        return self._api("admin/accounts/create", {
            "username": username,
            "password": password,
        })

    def login_as(self, username: str, password: str):
        """指定ユーザーでログインし、トークンを差し替える (Misskey 2025.x)。"""
        resp = self.http.post("/api/signin-flow", json={
            "username": username,
            "password": password,
        })
        resp.raise_for_status()
        data = resp.json()
        self.token = data.get("i") or data.get("token")
        return data

    def update_also_known_as(self, also_known_as: list[str]):
        """alsoKnownAs を設定する。"""
        payload = {"alsoKnownAs": also_known_as}
        if self.token:
            payload["i"] = self.token
        resp = self.http.post("/api/i/update", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(
                f"i/update failed ({resp.status_code}): {resp.text[:500]}"
            )
        return resp.json()

    def move(self, move_to_account: str, password: str):
        """アカウント移行を実行する (moveToAccount は acct 形式)。"""
        payload = {"moveToAccount": move_to_account, "password": password}
        if self.token:
            payload["i"] = self.token
        resp = self.http.post("/api/i/move", json=payload)
        if resp.status_code != 200:
            raise RuntimeError(
                f"i/move failed ({resp.status_code}): {resp.text[:500]}"
            )
        return resp.json() if resp.content else {}

    def get_user_info(self):
        """自分のアカウント情報を取得する。"""
        return self._api("i")


@pytest.fixture(scope="session", autouse=True)
def wait_for_instances():
    """Wait for both instances to be healthy."""
    wait_for_health(NEKO_URL, "/api/v1/health")
    wait_for_health(MISSKEY_URL, "/api/ping", method="POST")


@pytest.fixture(scope="session")
def neko() -> NekoClient:
    return NekoClient(NEKO_URL, NEKO_DOMAIN)


@pytest.fixture(scope="session")
def misskey() -> MisskeyClient:
    return MisskeyClient(MISSKEY_URL, MISSKEY_DOMAIN)


@pytest.fixture(scope="session")
def alice(neko: NekoClient) -> dict:
    """Register alice on Nekonoverse."""
    user = neko.register("alice", "alice@example.com", "password1234", "Alice")
    neko.login("alice", "password1234")
    return user


@pytest.fixture(scope="session")
def bob(misskey: MisskeyClient) -> dict:
    """Create bob on Misskey (first user = admin)."""
    user = misskey.create_admin("bob", "password1234")
    return user
