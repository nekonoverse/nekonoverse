"""Discord 互換 Webhook 通知設定の API エンドポイント。"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.discord_webhook import DiscordWebhook
from app.models.user import User
from app.schemas.discord_webhook import (
    DiscordWebhookCreateRequest,
    DiscordWebhookResponse,
    DiscordWebhookTestResponse,
    DiscordWebhookUpdateRequest,
)
from app.services.discord_webhook_service import (
    create_webhook,
    delete_webhook,
    get_webhook,
    is_safe_webhook_target,
    list_webhooks,
    mask_webhook_url,
    send_test_payload,
    update_webhook,
)

router = APIRouter(prefix="/api/v1/discord-webhooks", tags=["discord-webhooks"])


def _to_response(webhook: DiscordWebhook) -> DiscordWebhookResponse:
    return DiscordWebhookResponse(
        id=webhook.id,
        name=webhook.name,
        webhook_url_masked=mask_webhook_url(webhook.webhook_url),
        notify_mention=webhook.notify_mention,
        notify_direct=webhook.notify_direct,
        notify_quote=webhook.notify_quote,
        notify_reaction=webhook.notify_reaction,
        notify_renote=webhook.notify_renote,
        notify_follow=webhook.notify_follow,
        notify_follow_request=webhook.notify_follow_request,
        enabled=webhook.enabled,
        consecutive_failures=webhook.consecutive_failures,
        last_error=webhook.last_error,
        last_delivered_at=webhook.last_delivered_at,
        created_at=webhook.created_at,
        updated_at=webhook.updated_at,
    )


@router.get("", response_model=list[DiscordWebhookResponse])
async def list_my_webhooks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    webhooks = await list_webhooks(db, user.id)
    return [_to_response(w) for w in webhooks]


@router.post("", response_model=DiscordWebhookResponse, status_code=201)
async def create_my_webhook(
    body: DiscordWebhookCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    url = str(body.webhook_url)
    if not await is_safe_webhook_target(url):
        raise HTTPException(
            status_code=400,
            detail="Webhook URL must resolve to a public host",
        )
    try:
        webhook = await create_webhook(
            db,
            user.id,
            name=body.name,
            webhook_url=url,
            notify_mention=body.notify_mention,
            notify_direct=body.notify_direct,
            notify_quote=body.notify_quote,
            notify_reaction=body.notify_reaction,
            notify_renote=body.notify_renote,
            notify_follow=body.notify_follow,
            notify_follow_request=body.notify_follow_request,
            enabled=body.enabled,
        )
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Webhook URL already registered")
    await db.refresh(webhook)
    return _to_response(webhook)


@router.get("/{webhook_id}", response_model=DiscordWebhookResponse)
async def get_my_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    webhook = await get_webhook(db, user.id, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    return _to_response(webhook)


@router.patch("/{webhook_id}", response_model=DiscordWebhookResponse)
async def update_my_webhook(
    webhook_id: uuid.UUID,
    body: DiscordWebhookUpdateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    webhook = await get_webhook(db, user.id, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    updates = body.model_dump(exclude_unset=True)
    if "webhook_url" in updates and updates["webhook_url"] is not None:
        updates["webhook_url"] = str(updates["webhook_url"])
        if not await is_safe_webhook_target(updates["webhook_url"]):
            raise HTTPException(
                status_code=400,
                detail="Webhook URL must resolve to a public host",
            )
    try:
        await update_webhook(db, webhook, updates)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Webhook URL already registered")
    await db.refresh(webhook)
    return _to_response(webhook)


@router.delete("/{webhook_id}", status_code=204)
async def delete_my_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    webhook = await get_webhook(db, user.id, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    await delete_webhook(db, webhook)
    await db.commit()


@router.post("/{webhook_id}/test", response_model=DiscordWebhookTestResponse)
async def test_my_webhook(
    webhook_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    webhook = await get_webhook(db, user.id, webhook_id)
    if webhook is None:
        raise HTTPException(status_code=404, detail="Webhook not found")
    success, status_code, error = await send_test_payload(webhook)
    return DiscordWebhookTestResponse(
        success=success, status_code=status_code, error=error
    )
