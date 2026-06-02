"""Discord 互換 Webhook 通知サービスの単体テスト。"""

import asyncio
from unittest.mock import patch

import pytest
from sqlalchemy import select

from app.models.actor import Actor
from app.models.discord_webhook import DiscordWebhook
from app.models.notification import Notification
from app.services.discord_webhook_service import (
    _select_notify_column,
    dispatch_webhooks,
    mask_webhook_url,
)
from tests.conftest import make_note


@pytest.mark.parametrize(
    "notification_type, visibility, expected_column",
    [
        ("mention", "public", "notify_mention"),
        ("mention", "unlisted", "notify_mention"),
        ("mention", "followers", "notify_mention"),
        ("mention", "direct", "notify_direct"),
        ("reply", "public", "notify_mention"),
        ("reply", "direct", "notify_direct"),
        ("quote", None, "notify_quote"),
        ("reaction", None, "notify_reaction"),
        ("renote", None, "notify_renote"),
        ("follow", None, "notify_follow"),
        ("follow_request", None, "notify_follow_request"),
        ("poll", None, None),
        ("unknown", None, None),
    ],
)
def test_select_notify_column(notification_type, visibility, expected_column):
    assert _select_notify_column(notification_type, visibility) == expected_column


def test_mask_webhook_url_discord_format():
    url = "https://discord.com/api/webhooks/1234567890/abcdefghijklmnop"
    masked = mask_webhook_url(url)
    assert masked.startswith("https://discord.com/api/webhooks/1234567890/***")
    # 末尾 4 文字だけ残す
    assert masked.endswith("mnop")
    # 中間トークンは隠す (abc/cdef 等は出てこない)
    assert "abcdefghijkl" not in masked


def test_mask_webhook_url_short():
    assert mask_webhook_url("xx") == "***"


async def test_is_safe_webhook_target_rejects_localhost():
    from app.services.discord_webhook_service import is_safe_webhook_target

    assert not await is_safe_webhook_target("http://127.0.0.1/x")
    assert not await is_safe_webhook_target("http://localhost/x")
    assert not await is_safe_webhook_target("http://10.0.0.1/x")
    assert not await is_safe_webhook_target("http://192.168.1.1/x")
    assert not await is_safe_webhook_target("http://169.254.169.254/x")
    assert not await is_safe_webhook_target("http://[::1]/x")
    assert not await is_safe_webhook_target("http://foo.local/x")
    # スキームが http/https でない
    assert not await is_safe_webhook_target("file:///etc/passwd")


async def test_is_safe_webhook_target_accepts_public(mock_valkey):
    from unittest.mock import patch as _patch

    # DNS 解決をモックして公開 IP を返す
    fake_infos = [(2, 1, 6, "", ("1.2.3.4", 0))]

    class _Loop:
        async def getaddrinfo(self, *args, **kwargs):
            return fake_infos

    from app.services.discord_webhook_service import is_safe_webhook_target

    with _patch(
        "app.services.discord_webhook_service.asyncio.get_running_loop",
        return_value=_Loop(),
    ):
        assert await is_safe_webhook_target("https://discord.com/api/webhooks/1/abc")


async def _get_actor(db, actor_id):
    return (await db.execute(select(Actor).where(Actor.id == actor_id))).scalar_one()


async def test_dispatch_filters_by_notify_column(db, test_user):
    actor = await _get_actor(db, test_user.actor_id)

    db.add_all(
        [
            DiscordWebhook(
                user_id=test_user.id,
                name="mention only",
                webhook_url="https://example.com/webhook/mention",
                notify_mention=True,
                notify_direct=False,
                notify_quote=False,
                notify_reaction=False,
                notify_renote=False,
                notify_follow=False,
                notify_follow_request=False,
            ),
            DiscordWebhook(
                user_id=test_user.id,
                name="reaction only",
                webhook_url="https://example.com/webhook/reaction",
                notify_mention=False,
                notify_direct=False,
                notify_quote=False,
                notify_reaction=True,
                notify_renote=False,
                notify_follow=False,
                notify_follow_request=False,
            ),
        ]
    )
    await db.flush()

    note = await make_note(db, actor, visibility="public", content="hi")
    notification = Notification(
        type="mention", recipient_id=actor.id, sender_id=actor.id, note_id=note.id
    )
    db.add(notification)
    await db.flush()

    posted_urls: list[str] = []

    async def fake_deliver(webhook_id, url, payload):
        posted_urls.append(url)

    with patch(
        "app.services.discord_webhook_service._deliver", side_effect=fake_deliver
    ):
        await dispatch_webhooks(db, notification, sender=actor, note=note)
        # asyncio.create_task の実行を 1 ティック進める
        await asyncio.sleep(0)

    assert posted_urls == ["https://example.com/webhook/mention"]


async def test_dispatch_direct_visibility_uses_notify_direct(db, test_user):
    actor = await _get_actor(db, test_user.actor_id)

    db.add(
        DiscordWebhook(
            user_id=test_user.id,
            name="all but direct",
            webhook_url="https://example.com/webhook/x",
            notify_mention=True,
            notify_direct=False,
            notify_quote=False,
            notify_reaction=False,
            notify_renote=False,
            notify_follow=False,
            notify_follow_request=False,
        )
    )
    await db.flush()

    note = await make_note(db, actor, visibility="direct", content="hi")
    notification = Notification(
        type="mention", recipient_id=actor.id, sender_id=actor.id, note_id=note.id
    )
    db.add(notification)
    await db.flush()

    posted_urls: list[str] = []

    async def fake_deliver(webhook_id, url, payload):
        posted_urls.append(url)

    with patch(
        "app.services.discord_webhook_service._deliver", side_effect=fake_deliver
    ):
        await dispatch_webhooks(db, notification, sender=actor, note=note)
        await asyncio.sleep(0)

    assert posted_urls == []


async def test_dispatch_skips_disabled_webhook(db, test_user):
    actor = await _get_actor(db, test_user.actor_id)

    db.add(
        DiscordWebhook(
            user_id=test_user.id,
            name="disabled",
            webhook_url="https://example.com/webhook/disabled",
            notify_mention=True,
            enabled=False,
        )
    )
    await db.flush()

    note = await make_note(db, actor, visibility="public", content="hi")
    notification = Notification(
        type="mention", recipient_id=actor.id, sender_id=actor.id, note_id=note.id
    )
    db.add(notification)
    await db.flush()

    posted_urls: list[str] = []

    async def fake_deliver(webhook_id, url, payload):
        posted_urls.append(url)

    with patch(
        "app.services.discord_webhook_service._deliver", side_effect=fake_deliver
    ):
        await dispatch_webhooks(db, notification, sender=actor, note=note)
        await asyncio.sleep(0)

    assert posted_urls == []


async def test_dispatch_skips_for_remote_recipient(db, test_user, mock_valkey):
    """recipient がリモートアクター (= User 行なし) の場合は何も配送しない。"""
    from tests.conftest import make_remote_actor

    remote_actor = await make_remote_actor(db, username="alice", domain="remote.example")

    # test_user は別 user として webhook を登録しているが、
    # remote_actor 宛通知では当然引かれない。
    db.add(
        DiscordWebhook(
            user_id=test_user.id,
            name="x",
            webhook_url="https://example.com/x",
            notify_mention=True,
        )
    )
    await db.flush()

    notification = Notification(
        type="mention", recipient_id=remote_actor.id, sender_id=None
    )
    db.add(notification)
    await db.flush()

    with patch("app.services.discord_webhook_service._deliver") as deliver_mock:
        await dispatch_webhooks(db, notification, sender=None, note=None)
        await asyncio.sleep(0)
    deliver_mock.assert_not_called()
