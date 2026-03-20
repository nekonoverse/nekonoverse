import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pytest

from app.models.oauth import OAuthApplication, OAuthToken


async def _create_app_with_token(db, user_id):
    """Create an OAuth app and an active token for the given user."""
    app = OAuthApplication(
        name="TestApp",
        client_id=secrets.token_urlsafe(32),
        client_secret=secrets.token_urlsafe(64),
        redirect_uris="http://localhost/callback",
        scopes="read write",
    )
    db.add(app)
    await db.flush()

    plain_token = secrets.token_urlsafe(32)
    token = OAuthToken(
        access_token=hashlib.sha256(plain_token.encode()).hexdigest(),
        scopes="read write",
        application_id=app.id,
        user_id=user_id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
    )
    db.add(token)
    await db.flush()
    return app, token


async def test_list_authorized_apps_empty(authed_client):
    resp = await authed_client.get("/api/v1/authorized_apps")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_authorized_apps(authed_client, db, test_user):
    app, _ = await _create_app_with_token(db, test_user.id)
    await db.commit()

    resp = await authed_client.get("/api/v1/authorized_apps")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["id"] == str(app.id)
    assert data[0]["name"] == "TestApp"
    assert data[0]["scopes"] == ["read", "write"]
    assert "created_at" in data[0]


async def test_list_excludes_revoked(authed_client, db, test_user):
    app, token = await _create_app_with_token(db, test_user.id)
    token.revoked_at = datetime.now(timezone.utc)
    await db.commit()

    resp = await authed_client.get("/api/v1/authorized_apps")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_excludes_expired(authed_client, db, test_user):
    app, token = await _create_app_with_token(db, test_user.id)
    token.expires_at = datetime.now(timezone.utc) - timedelta(days=1)
    await db.commit()

    resp = await authed_client.get("/api/v1/authorized_apps")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_revoke_authorized_app(authed_client, db, test_user):
    app, _ = await _create_app_with_token(db, test_user.id)
    await db.commit()

    resp = await authed_client.delete(f"/api/v1/authorized_apps/{app.id}")
    assert resp.status_code == 200

    # Should no longer appear in list
    resp2 = await authed_client.get("/api/v1/authorized_apps")
    assert resp2.json() == []


async def test_revoke_not_found(authed_client):
    import uuid

    resp = await authed_client.delete(
        f"/api/v1/authorized_apps/{uuid.uuid4()}"
    )
    assert resp.status_code == 404


async def test_revoke_does_not_affect_other_users(
    authed_client, db, test_user, test_user_b
):
    app, _ = await _create_app_with_token(db, test_user.id)
    # Also create a token for user B on the same app
    plain_token_b = secrets.token_urlsafe(32)
    token_b = OAuthToken(
        access_token=hashlib.sha256(plain_token_b.encode()).hexdigest(),
        scopes="read",
        application_id=app.id,
        user_id=test_user_b.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=90),
    )
    db.add(token_b)
    await db.commit()

    # User A revokes
    resp = await authed_client.delete(f"/api/v1/authorized_apps/{app.id}")
    assert resp.status_code == 200

    # User B's token should still be active
    await db.refresh(token_b)
    assert token_b.revoked_at is None


async def test_unauthenticated(app_client):
    resp = await app_client.get("/api/v1/authorized_apps")
    assert resp.status_code == 401
