"""Tests for Mastodon-compatible List API endpoints."""

import uuid

from app.models.actor import Actor
from app.services.list_service import add_list_member, create_list


def _make_actor(username="apitest"):
    return Actor(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/users/{username}",
        type="Person",
        username=username,
        domain=None,
        display_name=username,
        inbox_url=f"https://localhost/users/{username}/inbox",
        outbox_url=f"https://localhost/users/{username}/outbox",
        public_key_pem="-----BEGIN PUBLIC KEY-----\ntest\n-----END PUBLIC KEY-----",
    )


# -- List CRUD --


async def test_create_list(authed_client, db):
    resp = await authed_client.post("/api/v1/lists", json={"title": "My List"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "My List"
    assert data["replies_policy"] == "list"
    assert data["exclusive"] is False


async def test_create_list_with_options(authed_client, db):
    resp = await authed_client.post(
        "/api/v1/lists",
        json={"title": "Excl", "replies_policy": "none", "exclusive": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["replies_policy"] == "none"
    assert data["exclusive"] is True


async def test_create_list_invalid_title(authed_client, db):
    resp = await authed_client.post("/api/v1/lists", json={"title": ""})
    assert resp.status_code == 422


async def test_create_list_invalid_replies_policy(authed_client, db):
    resp = await authed_client.post(
        "/api/v1/lists", json={"title": "Bad", "replies_policy": "invalid"}
    )
    assert resp.status_code == 422


async def test_get_lists(authed_client, db, test_user):
    await create_list(db, test_user, "A")
    await create_list(db, test_user, "B")
    await db.commit()

    resp = await authed_client.get("/api/v1/lists")
    assert resp.status_code == 200
    data = resp.json()
    titles = [d["title"] for d in data]
    assert "A" in titles
    assert "B" in titles


async def test_get_single_list(authed_client, db, test_user):
    lst = await create_list(db, test_user, "Single")
    await db.commit()

    resp = await authed_client.get(f"/api/v1/lists/{lst.id}")
    assert resp.status_code == 200
    assert resp.json()["title"] == "Single"


async def test_get_list_not_found(authed_client, db):
    resp = await authed_client.get(f"/api/v1/lists/{uuid.uuid4()}")
    assert resp.status_code == 404


async def test_update_list(authed_client, db, test_user):
    lst = await create_list(db, test_user, "Old")
    await db.commit()

    resp = await authed_client.put(
        f"/api/v1/lists/{lst.id}",
        json={"title": "New", "exclusive": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["title"] == "New"
    assert data["exclusive"] is True


async def test_delete_list(authed_client, db, test_user):
    lst = await create_list(db, test_user, "Delete")
    await db.commit()

    resp = await authed_client.delete(f"/api/v1/lists/{lst.id}")
    assert resp.status_code == 200

    resp = await authed_client.get(f"/api/v1/lists/{lst.id}")
    assert resp.status_code == 404


# -- Members --


async def test_add_get_remove_accounts(authed_client, db, test_user):
    lst = await create_list(db, test_user, "Members")
    actor = _make_actor(username="member1")
    db.add(actor)
    await db.commit()

    # Add
    resp = await authed_client.post(
        f"/api/v1/lists/{lst.id}/accounts",
        json={"account_ids": [str(actor.id)]},
    )
    assert resp.status_code == 200

    # Get
    resp = await authed_client.get(f"/api/v1/lists/{lst.id}/accounts")
    assert resp.status_code == 200
    accounts = resp.json()
    assert any(a["id"] == str(actor.id) for a in accounts)

    # Remove
    resp = await authed_client.request(
        "DELETE",
        f"/api/v1/lists/{lst.id}/accounts",
        json={"account_ids": [str(actor.id)]},
    )
    assert resp.status_code == 200

    # Verify removed
    resp = await authed_client.get(f"/api/v1/lists/{lst.id}/accounts")
    assert len(resp.json()) == 0


# -- List Timeline --


async def test_list_timeline_endpoint(authed_client, db, test_user):
    from datetime import datetime, timezone

    from app.models.note import Note

    lst = await create_list(db, test_user, "Timeline")
    actor = _make_actor(username="tlposter")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)

    note = Note(
        id=uuid.uuid4(),
        ap_id=f"https://localhost/notes/{uuid.uuid4()}",
        actor_id=actor.id,
        content="<p>List post</p>",
        visibility="public",
        local=True,
        published=datetime.now(timezone.utc),
    )
    db.add(note)
    await db.commit()

    resp = await authed_client.get(f"/api/v1/timelines/list/{lst.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1


async def test_list_timeline_not_found(authed_client, db):
    resp = await authed_client.get(f"/api/v1/timelines/list/{uuid.uuid4()}")
    assert resp.status_code == 404


# -- Auth --


async def test_lists_require_auth(app_client, db):
    resp = await app_client.get("/api/v1/lists")
    assert resp.status_code in (401, 403)


# -- IDOR --


async def _create_other_users_list(db, title="Other's List"):
    """Helper: create a list owned by a different user (not test_user)."""
    from app.services.user_service import create_user

    other = await create_user(db, "otheruser", "other@test.com", "password1234")
    lst = await create_list(db, other, title)
    await db.commit()
    return other, lst


async def test_idor_get_list(authed_client, db):
    """GET another user's list returns 404, not 403 (no information leakage)."""
    _, lst = await _create_other_users_list(db)
    resp = await authed_client.get(f"/api/v1/lists/{lst.id}")
    assert resp.status_code == 404


async def test_idor_update_list(authed_client, db):
    """PUT another user's list is rejected."""
    _, lst = await _create_other_users_list(db)
    resp = await authed_client.put(
        f"/api/v1/lists/{lst.id}",
        json={"title": "Hacked"},
    )
    assert resp.status_code == 404


async def test_idor_delete_list(authed_client, db):
    """DELETE another user's list is rejected."""
    other, lst = await _create_other_users_list(db)
    resp = await authed_client.delete(f"/api/v1/lists/{lst.id}")
    assert resp.status_code == 404

    # Verify the list still exists for the real owner
    from app.services.list_service import get_list
    fetched = await get_list(db, lst.id)
    assert fetched is not None
    assert fetched.title == "Other's List"


async def test_idor_get_list_accounts(authed_client, db):
    """GET members of another user's list is rejected."""
    other, lst = await _create_other_users_list(db)
    actor = _make_actor(username="othermember")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)
    await db.commit()

    resp = await authed_client.get(f"/api/v1/lists/{lst.id}/accounts")
    assert resp.status_code == 404


async def test_idor_add_list_accounts(authed_client, db):
    """POST members to another user's list is rejected."""
    _, lst = await _create_other_users_list(db)
    actor = _make_actor(username="injected")
    db.add(actor)
    await db.commit()

    resp = await authed_client.post(
        f"/api/v1/lists/{lst.id}/accounts",
        json={"account_ids": [str(actor.id)]},
    )
    assert resp.status_code == 404

    # Verify no member was actually added
    from app.services.list_service import get_list_member_ids
    member_ids = await get_list_member_ids(db, lst.id)
    assert actor.id not in member_ids


async def test_idor_remove_list_accounts(authed_client, db):
    """DELETE members from another user's list is rejected."""
    other, lst = await _create_other_users_list(db)
    actor = _make_actor(username="victim_member")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)
    await db.commit()

    resp = await authed_client.request(
        "DELETE",
        f"/api/v1/lists/{lst.id}/accounts",
        json={"account_ids": [str(actor.id)]},
    )
    assert resp.status_code == 404

    # Verify member was not removed
    from app.services.list_service import get_list_member_ids
    member_ids = await get_list_member_ids(db, lst.id)
    assert actor.id in member_ids


async def test_idor_list_timeline(authed_client, db):
    """GET timeline of another user's list is rejected."""
    _, lst = await _create_other_users_list(db)
    resp = await authed_client.get(f"/api/v1/timelines/list/{lst.id}")
    assert resp.status_code == 404


async def test_idor_list_not_leaked_in_index(authed_client, db, test_user):
    """GET /api/v1/lists only returns the current user's lists, not others'."""
    from app.services.user_service import create_user

    other = await create_user(db, "leakuser", "leak@test.com", "password1234")
    await create_list(db, other, "Secret List")
    await create_list(db, test_user, "My List")
    await db.commit()

    resp = await authed_client.get("/api/v1/lists")
    assert resp.status_code == 200
    data = resp.json()
    titles = [d["title"] for d in data]
    assert "My List" in titles
    assert "Secret List" not in titles


async def test_idor_update_preserves_data(authed_client, db):
    """IDOR update attempt does not alter the original list's data."""
    other, lst = await _create_other_users_list(db, title="Original")
    original_id = lst.id

    resp = await authed_client.put(
        f"/api/v1/lists/{original_id}",
        json={"title": "Tampered", "replies_policy": "none", "exclusive": True},
    )
    assert resp.status_code == 404

    # Verify data unchanged
    from app.services.list_service import get_list
    fetched = await get_list(db, original_id)
    assert fetched.title == "Original"
    assert fetched.replies_policy == "list"
    assert fetched.exclusive is False


async def test_unauthed_all_list_endpoints(app_client, db):
    """All list endpoints require authentication."""
    fake_id = str(uuid.uuid4())

    endpoints = [
        ("GET", "/api/v1/lists"),
        ("POST", "/api/v1/lists"),
        ("GET", f"/api/v1/lists/{fake_id}"),
        ("PUT", f"/api/v1/lists/{fake_id}"),
        ("DELETE", f"/api/v1/lists/{fake_id}"),
        ("GET", f"/api/v1/lists/{fake_id}/accounts"),
        ("POST", f"/api/v1/lists/{fake_id}/accounts"),
        ("DELETE", f"/api/v1/lists/{fake_id}/accounts"),
        ("GET", f"/api/v1/timelines/list/{fake_id}"),
    ]
    for method, path in endpoints:
        resp = await app_client.request(method, path)
        assert resp.status_code in (401, 403), (
            f"{method} {path} returned {resp.status_code}, expected 401/403"
        )


# -- GET /api/v1/accounts/:id/lists --


async def test_account_lists_member(authed_client, db, test_user):
    """Lists containing the account are returned."""
    lst = await create_list(db, test_user, "Contains")
    actor = _make_actor(username="inlist")
    db.add(actor)
    await db.commit()
    await add_list_member(db, lst, actor)
    await db.commit()

    resp = await authed_client.get(f"/api/v1/accounts/{actor.id}/lists")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(lst.id)
    assert data[0]["title"] == "Contains"


async def test_account_lists_empty(authed_client, db, test_user):
    """Empty list when account is not in any list."""
    actor = _make_actor(username="notinlist")
    db.add(actor)
    await db.commit()

    resp = await authed_client.get(f"/api/v1/accounts/{actor.id}/lists")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_account_lists_unauthenticated(app_client, db):
    """Unauthenticated request returns 401."""
    fake_id = str(uuid.uuid4())
    resp = await app_client.get(f"/api/v1/accounts/{fake_id}/lists")
    assert resp.status_code in (401, 403)
