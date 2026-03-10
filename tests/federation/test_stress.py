"""Stress tests for federation display — bulk notes, reactions, and timeline rendering.

Targets display issues by creating high-volume data and verifying consistency.
"""

import concurrent.futures
import time

import httpx
import pytest

from conftest import (
    INSTANCE_A,
    INSTANCE_A_DOMAIN,
    INSTANCE_B,
    INSTANCE_B_DOMAIN,
    InstanceClient,
    poll_until,
)

STRESS_NOTE_COUNT = 50
CONCURRENT_USERS = 5


@pytest.fixture(scope="module")
def client_a() -> InstanceClient:
    return InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)


@pytest.fixture(scope="module")
def client_b() -> InstanceClient:
    return InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)


@pytest.fixture(scope="module")
def stress_users_a(client_a: InstanceClient) -> list[dict]:
    """Register multiple users on instance A."""
    users = []
    for i in range(CONCURRENT_USERS):
        username = f"stress_a_{i}"
        try:
            user = client_a.register(username, f"{username}@example.com", "password1234", f"Stress User A{i}")
            users.append(user)
        except httpx.HTTPStatusError:
            pass  # Already exists from previous run
    # Login as the first user for API calls
    client_a.login("stress_a_0", "password1234")
    return users


@pytest.fixture(scope="module")
def stress_users_b(client_b: InstanceClient) -> list[dict]:
    """Register multiple users on instance B."""
    users = []
    for i in range(CONCURRENT_USERS):
        username = f"stress_b_{i}"
        try:
            user = client_b.register(username, f"{username}@example.com", "password1234", f"Stress User B{i}")
            users.append(user)
        except httpx.HTTPStatusError:
            pass
    client_b.login("stress_b_0", "password1234")
    return users


class TestBulkNoteCreation:
    """Rapid note creation to test timeline display under load."""

    def test_bulk_create_notes_instance_a(self, client_a: InstanceClient, stress_users_a):
        """Create many notes rapidly on instance A."""
        created = []
        for i in range(STRESS_NOTE_COUNT):
            note = client_a.create_note(
                f"Stress test note #{i} — " + "あ" * (i % 50) + f" @stress_a_{i % CONCURRENT_USERS}"
            )
            created.append(note)
        assert len(created) == STRESS_NOTE_COUNT

    def test_bulk_create_notes_instance_b(self, client_b: InstanceClient, stress_users_b):
        """Create many notes rapidly on instance B."""
        created = []
        for i in range(STRESS_NOTE_COUNT):
            note = client_b.create_note(
                f"Stress test note #{i} from B — " + "🐱" * (i % 20)
            )
            created.append(note)
        assert len(created) == STRESS_NOTE_COUNT


class TestTimelineConsistency:
    """Verify timeline returns correct data under volume."""

    def test_timeline_pagination_a(self, client_a: InstanceClient, stress_users_a):
        """Paginate through all notes on instance A, verify no duplicates or gaps."""
        all_ids = set()
        all_notes = []
        max_id = None
        pages = 0

        while pages < 20:  # Safety limit
            params = {"local": "true", "limit": "20"}
            if max_id:
                params["max_id"] = max_id
            resp = client_a.http.get("/api/v1/timelines/public", params=params)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for note in batch:
                assert note["id"] not in all_ids, f"Duplicate note ID: {note['id']} on page {pages}"
                all_ids.add(note["id"])
                all_notes.append(note)
            max_id = batch[-1]["id"]
            pages += 1

        assert len(all_notes) >= STRESS_NOTE_COUNT, (
            f"Expected at least {STRESS_NOTE_COUNT} notes, got {len(all_notes)}"
        )

    def test_timeline_pagination_b(self, client_b: InstanceClient, stress_users_b):
        """Paginate through all notes on instance B."""
        all_ids = set()
        all_notes = []
        max_id = None
        pages = 0

        while pages < 20:
            params = {"local": "true", "limit": "20"}
            if max_id:
                params["max_id"] = max_id
            resp = client_b.http.get("/api/v1/timelines/public", params=params)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for note in batch:
                assert note["id"] not in all_ids, f"Duplicate note ID: {note['id']}"
                all_ids.add(note["id"])
                all_notes.append(note)
            max_id = batch[-1]["id"]
            pages += 1

        assert len(all_notes) >= STRESS_NOTE_COUNT

    def test_timeline_order_is_chronological(self, client_a: InstanceClient, stress_users_a):
        """Notes should be in reverse chronological order."""
        resp = client_a.http.get("/api/v1/timelines/public", params={"local": "true", "limit": "40"})
        resp.raise_for_status()
        notes = resp.json()
        assert len(notes) >= 2

        for i in range(len(notes) - 1):
            assert notes[i]["published"] >= notes[i + 1]["published"], (
                f"Note order broken at index {i}: "
                f"{notes[i]['published']} < {notes[i+1]['published']}"
            )


class TestNoteContentVariants:
    """Test display of various content types."""

    def test_long_content(self, client_a: InstanceClient, stress_users_a):
        """Very long note content."""
        long_text = "This is a long note. " * 200  # ~4200 chars
        note = client_a.create_note(long_text)
        fetched = client_a.get_note(note["id"])
        assert len(fetched["content"]) > 1000

    def test_unicode_heavy_content(self, client_a: InstanceClient, stress_users_a):
        """Notes with heavy Unicode (CJK, emoji, combining chars)."""
        contents = [
            "日本語テスト 🇯🇵 テスト投稿です。絵文字: 😀🎉🐱‍👤",
            "한국어 테스트 🇰🇷 이것은 테스트입니다",
            "中文测试 🇨🇳 这是一个测试帖子",
            "Zalgo t̷̢̧͎̞͈̣̼̤̫̤͙̰̗̖̉̃̌̽̀̋̓̅̃̈̕͝ę̸̛̱̣̦̻̭̗̼̬̱̏̈́̌̄̇̐͑̅̃̕͝s̸̙̈́t̶̨̜̬̖̰͙̗̦̠̘̣̼̓͊̇́̾͛̚",
            "Emoji spam: " + "".join(chr(0x1F600 + i) for i in range(50)),
        ]
        for content in contents:
            note = client_a.create_note(content)
            fetched = client_a.get_note(note["id"])
            assert fetched["content"] is not None
            assert fetched["id"] == note["id"]

    def test_html_entities_in_content(self, client_a: InstanceClient, stress_users_a):
        """Content with HTML-like strings (should be sanitized)."""
        note = client_a.create_note('<script>alert("xss")</script> & "quotes" <b>bold</b>')
        fetched = client_a.get_note(note["id"])
        assert "<script>" not in fetched["content"]

    def test_empty_and_whitespace_notes(self, client_a: InstanceClient, stress_users_a):
        """Whitespace-only notes — server should reject or handle gracefully."""
        for content in ["   ", "\n\n\n", "\t"]:
            resp = client_a.http.post(
                "/api/v1/statuses", json={"content": content, "visibility": "public"}
            )
            # Either 400 (rejected) or 201 (accepted) — should not 500
            assert resp.status_code in (201, 400, 422), f"Unexpected status: {resp.status_code}"


class TestBulkReactions:
    """Stress test emoji reactions."""

    def test_rapid_react_unreact(self, client_a: InstanceClient, stress_users_a):
        """Rapid react/unreact cycle on a single note."""
        note = client_a.create_note("Reaction stress test target")
        note_id = note["id"]
        emojis = ["👍", "❤️", "😂", "🎉", "🐱"]

        for emoji in emojis:
            client_a.react(note_id, emoji)

        fetched = client_a.get_note(note_id)
        assert fetched["reactions_count"] >= len(emojis)

        for emoji in emojis:
            client_a.unreact(note_id, emoji)

        fetched = client_a.get_note(note_id)
        assert fetched["reactions_count"] == 0

    def test_many_reactions_on_many_notes(self, client_a: InstanceClient, stress_users_a):
        """React to multiple notes in rapid succession."""
        notes = []
        for i in range(10):
            notes.append(client_a.create_note(f"Multi-reaction target #{i}"))

        for note in notes:
            client_a.react(note["id"], "⭐")

        for note in notes:
            fetched = client_a.get_note(note["id"])
            assert fetched["reactions_count"] >= 1


class TestConcurrentRequests:
    """Simulate concurrent API access."""

    def test_concurrent_timeline_reads(self, client_a: InstanceClient, stress_users_a):
        """Multiple concurrent timeline reads should all succeed."""
        def fetch_timeline():
            c = httpx.Client(base_url=INSTANCE_A, timeout=15)
            resp = c.get("/api/v1/timelines/public", params={"local": "true", "limit": "20"})
            c.close()
            return resp.status_code, len(resp.json())

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_timeline) for _ in range(20)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        for status, count in results:
            assert status == 200, f"Timeline request failed with status {status}"
            assert count > 0

    def test_concurrent_note_creation(self, stress_users_a):
        """Multiple users creating notes concurrently."""
        def create_note_as_user(user_idx: int):
            c = httpx.Client(base_url=INSTANCE_A, timeout=15)
            username = f"stress_a_{user_idx}"
            c.post("/api/v1/auth/login", json={"username": username, "password": "password1234"})
            resp = c.post(
                "/api/v1/statuses",
                json={"content": f"Concurrent note from {username}", "visibility": "public"},
            )
            c.close()
            return resp.status_code

        with concurrent.futures.ThreadPoolExecutor(max_workers=CONCURRENT_USERS) as executor:
            futures = [executor.submit(create_note_as_user, i) for i in range(CONCURRENT_USERS)]
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        for status in results:
            assert status == 201, f"Concurrent note creation failed with status {status}"


class TestAPEndpointsUnderLoad:
    """ActivityPub endpoints with many objects."""

    def test_outbox_with_many_notes(self, client_a: InstanceClient, stress_users_a):
        """Outbox should list all notes without errors."""
        resp = client_a.http.get(
            "/users/stress_a_0/outbox",
            params={"page": "true"},
            headers={"Accept": "application/activity+json"},
        )
        assert resp.status_code == 200
        page = resp.json()
        assert page["type"] == "OrderedCollectionPage"
        assert len(page["orderedItems"]) > 0

    def test_outbox_collection_total(self, client_a: InstanceClient, stress_users_a):
        """Outbox totalItems should match created notes."""
        resp = client_a.http.get(
            "/users/stress_a_0/outbox",
            headers={"Accept": "application/activity+json"},
        )
        assert resp.status_code == 200
        outbox = resp.json()
        assert outbox["type"] == "OrderedCollection"
        assert outbox["totalItems"] >= STRESS_NOTE_COUNT

    def test_individual_note_ap_endpoints(self, client_a: InstanceClient, stress_users_a):
        """Fetch individual notes via AP endpoint — sample 10 from timeline."""
        tl = client_a.public_timeline(local=True)
        sample = tl[:10]
        for note in sample:
            resp = client_a.http.get(
                f"/notes/{note['id']}",
                headers={"Accept": "application/activity+json"},
            )
            assert resp.status_code == 200
            ap_note = resp.json()
            assert ap_note["type"] == "Note"


class TestCrossInstanceDisplay:
    """Verify cross-instance data visibility."""

    def test_cross_fetch_notes_from_b(self, client_b: InstanceClient, stress_users_b):
        """Fetch instance B's notes from the network (simulating instance A fetching)."""
        # Paginate to collect all notes
        all_notes = []
        max_id = None
        for _ in range(10):
            params = {"local": "true", "limit": "40"}
            if max_id:
                params["max_id"] = max_id
            resp = client_b.http.get("/api/v1/timelines/public", params=params)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            all_notes.extend(batch)
            max_id = batch[-1]["id"]
        assert len(all_notes) >= STRESS_NOTE_COUNT

        # Fetch first 10 via AP
        for note in all_notes[:10]:
            resp = httpx.get(
                f"{INSTANCE_B}/notes/{note['id']}",
                headers={"Accept": "application/activity+json"},
                timeout=10,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["type"] == "Note"

    def test_actor_endpoints_under_load(self):
        """Fetch multiple actor endpoints concurrently across instances."""
        def fetch_actor(base_url: str, username: str):
            resp = httpx.get(
                f"{base_url}/users/{username}",
                headers={"Accept": "application/activity+json"},
                timeout=10,
            )
            return resp.status_code, resp.json().get("preferredUsername")

        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i in range(CONCURRENT_USERS):
                futures.append(executor.submit(fetch_actor, INSTANCE_A, f"stress_a_{i}"))
                futures.append(executor.submit(fetch_actor, INSTANCE_B, f"stress_b_{i}"))
            results = [f.result() for f in concurrent.futures.as_completed(futures)]

        for status, username in results:
            assert status == 200, f"Actor fetch failed: {status}"
            assert username is not None
