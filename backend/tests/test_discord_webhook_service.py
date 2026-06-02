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
    assert masked.startswith("https://discord.com/api/webhooks/1234567890/abcd")
    assert masked.endswith("***")
    assert "abcdefghijklmnop" not in masked


def test_mask_webhook_url_short():
    assert mask_webhook_url("xx") == "***"


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
