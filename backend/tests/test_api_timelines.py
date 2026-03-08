async def test_public_timeline(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={"content": "tl1", "visibility": "public"})
    await authed_client.post("/api/v1/statuses", json={"content": "tl2", "visibility": "public"})
    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    assert len(resp.json()) >= 2


async def test_public_timeline_local_filter(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={"content": "local", "visibility": "public"})
    resp = await authed_client.get("/api/v1/timelines/public", params={"local": "true"})
    assert resp.status_code == 200


async def test_public_timeline_limit(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/timelines/public", params={"limit": "1"})
    assert resp.status_code == 200
    assert len(resp.json()) <= 1


async def test_home_timeline_unauthenticated(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/timelines/home")
    assert resp.status_code == 401


async def test_home_timeline(authed_client, mock_valkey):
    resp = await authed_client.get("/api/v1/timelines/home")
    assert resp.status_code == 200


async def test_public_timeline_no_auth_ok(app_client, mock_valkey):
    resp = await app_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200


async def test_public_timeline_pagination(authed_client, mock_valkey):
    # Create 3 notes
    ids = []
    for i in range(3):
        resp = await authed_client.post("/api/v1/statuses", json={
            "content": f"page{i}", "visibility": "public"
        })
        ids.append(resp.json()["id"])

    # Get first page with limit 2
    resp = await authed_client.get("/api/v1/timelines/public", params={"limit": "2"})
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) <= 2

    # Use max_id from last item to get next page
    if len(data) == 2:
        last_id = data[-1]["id"]
        resp2 = await authed_client.get(
            "/api/v1/timelines/public",
            params={"limit": "2", "max_id": last_id},
        )
        assert resp2.status_code == 200


async def test_public_timeline_excludes_private(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={
        "content": "Public visible", "visibility": "public"
    })
    await authed_client.post("/api/v1/statuses", json={
        "content": "Private hidden", "visibility": "followers"
    })
    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    contents = [n["content"] for n in resp.json()]
    assert any("Public visible" in c for c in contents)
    assert not any("Private hidden" in c for c in contents)


async def test_home_timeline_returns_notes(authed_client, mock_valkey):
    await authed_client.post("/api/v1/statuses", json={
        "content": "Home note", "visibility": "public"
    })
    resp = await authed_client.get("/api/v1/timelines/home")
    assert resp.status_code == 200
    assert len(resp.json()) >= 1


async def test_public_timeline_includes_reactions(authed_client, mock_valkey):
    create_resp = await authed_client.post("/api/v1/statuses", json={
        "content": "TL reactions", "visibility": "public"
    })
    note_id = create_resp.json()["id"]
    await authed_client.post(f"/api/v1/statuses/{note_id}/react/❤️")

    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    for note in resp.json():
        if note["id"] == note_id:
            assert len(note["reactions"]) >= 1
            break


async def test_home_timeline_shows_own_notes(authed_client, mock_valkey):
    """Home timeline should include the user's own notes."""
    await authed_client.post("/api/v1/statuses", json={
        "content": "My own note", "visibility": "public"
    })
    resp = await authed_client.get("/api/v1/timelines/home")
    assert resp.status_code == 200
    contents = [n["content"] for n in resp.json()]
    assert any("My own note" in c for c in contents)


async def test_home_timeline_shows_followed_user(
    authed_client, test_user_b, db, mock_valkey
):
    """Home timeline should include notes from followed users."""
    # Follow test_user_b
    await authed_client.post(f"/api/v1/accounts/{test_user_b.actor_id}/follow")

    # Create a note for test_user_b
    from sqlalchemy import select
    from app.models.actor import Actor
    result = await db.execute(select(Actor).where(Actor.id == test_user_b.actor_id))
    actor_b = result.scalar_one()

    from tests.conftest import make_note
    await make_note(db, actor_b, content="Followed user note")
    await db.commit()

    resp = await authed_client.get("/api/v1/timelines/home")
    assert resp.status_code == 200
    contents = [n["content"] for n in resp.json()]
    assert any("Followed user note" in c for c in contents)


async def test_public_timeline_excludes_unlisted(authed_client, mock_valkey):
    """Unlisted notes should not appear on the public timeline."""
    await authed_client.post("/api/v1/statuses", json={
        "content": "Unlisted hidden from TL", "visibility": "unlisted"
    })
    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    contents = [n["content"] for n in resp.json()]
    assert not any("Unlisted hidden from TL" in c for c in contents)


async def test_public_timeline_excludes_direct(authed_client, mock_valkey):
    """Direct messages should not appear on the public timeline."""
    await authed_client.post("/api/v1/statuses", json={
        "content": "Direct hidden from TL", "visibility": "direct"
    })
    resp = await authed_client.get("/api/v1/timelines/public")
    assert resp.status_code == 200
    contents = [n["content"] for n in resp.json()]
    assert not any("Direct hidden from TL" in c for c in contents)
