"""認証まわりの堅牢化 (パスワードリセット時の失効、TOTP のユーザー単位制限) の回帰テスト。"""

import uuid
from unittest.mock import AsyncMock, patch

import pyotp
from sqlalchemy import select

from app.models.oauth import OAuthApplication, OAuthToken


class _FakeValkey:
    """get/set/incr/expire/delete だけを持つ辞書ベースの Valkey 代替。"""

    def __init__(self) -> None:
        self.data: dict[str, str] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, *args, **kwargs):
        self.data[key] = str(value)
        return True

    async def incr(self, key):
        self.data[key] = str(int(self.data.get(key, "0")) + 1)
        return int(self.data[key])

    async def expire(self, key, ttl, *args, **kwargs):
        return True

    async def delete(self, *keys):
        for key in keys:
            self.data.pop(key, None)
        return 1


async def test_reset_password_revokes_sessions_and_tokens(app_client, db, test_user, mock_valkey):
    app = OAuthApplication(
        name="client", client_id="cid-reset", client_secret="x", redirect_uris="urn:x"
    )
    db.add(app)
    await db.flush()
    token = OAuthToken(
        access_token="tok-reset", scopes="read", application_id=app.id, user_id=test_user.id
    )
    db.add(token)
    await db.flush()

    with (
        patch("app.api.email_verification._check_rate_limit", AsyncMock(return_value=True)),
        patch(
            "app.services.email_service.verify_reset_token",
            AsyncMock(return_value=test_user),
        ),
        patch(
            "app.services.moderation_service.invalidate_user_sessions", AsyncMock()
        ) as invalidate,
    ):
        resp = await app_client.post(
            "/api/v1/auth/reset-password",
            json={"uid": str(test_user.id), "token": "t", "password": "newpassword123"},
        )

    assert resp.status_code == 200
    invalidate.assert_awaited_once_with(test_user.id)
    row = await db.execute(select(OAuthToken).where(OAuthToken.access_token == "tok-reset"))
    assert row.scalar_one().revoked_at is not None


async def test_login_to_deleted_account_is_plain_401(app_client, db, test_user, mock_valkey):
    """削除済みアカウントへのログインは 500 にならず、存在しないユーザーと同じ 401。"""
    test_user.password_hash = "!deleted"
    await db.commit()

    resp = await app_client.post(
        "/api/v1/auth/login", json={"username": "testuser", "password": "password1234"}
    )
    assert resp.status_code == 401
    missing = await app_client.post(
        "/api/v1/auth/login", json={"username": "nobody", "password": "password1234"}
    )
    assert missing.status_code == 401
    assert resp.json() == missing.json()


async def test_totp_user_lockout_survives_new_pending_tokens(app_client, db, test_user):
    """保留トークンを取り直してもユーザー単位の失敗回数で止まる。"""
    from app.services.totp_service import TOTP_USER_MAX_FAILURES, encrypt_secret

    secret = pyotp.random_base32()
    test_user.totp_enabled = True
    test_user.totp_secret = encrypt_secret(secret)
    await db.commit()

    fake = _FakeValkey()
    wrong = f"{(int(pyotp.TOTP(secret).now()) + 500000) % 1000000:06d}"
    with patch("app.valkey_client.valkey", fake):
        statuses = []
        for _ in range(TOTP_USER_MAX_FAILURES + 1):
            pending = uuid.uuid4().hex
            fake.data[f"totp_pending:{pending}"] = str(test_user.id)
            resp = await app_client.post(
                "/api/v1/auth/totp/verify", json={"totp_token": pending, "code": wrong}
            )
            statuses.append(resp.status_code)

        assert statuses == [401] * TOTP_USER_MAX_FAILURES + [429]

        # 正しいコードでもロック中は通らない
        pending = uuid.uuid4().hex
        fake.data[f"totp_pending:{pending}"] = str(test_user.id)
        resp = await app_client.post(
            "/api/v1/auth/totp/verify",
            json={"totp_token": pending, "code": pyotp.TOTP(secret).now()},
        )
        assert resp.status_code == 429
