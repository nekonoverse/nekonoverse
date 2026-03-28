"""Mastodon 互換 Web Push サブスクリプション API。"""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.push_service import (
    create_subscription,
    delete_subscription,
    get_subscription_by_session,
    get_vapid_public_key_base64url,
    update_subscription_alerts,
)

router = APIRouter(prefix="/api/v1/push", tags=["push"])


class SubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionParam(BaseModel):
    endpoint: str
    keys: SubscriptionKeys


class AlertsParam(BaseModel):
    mention: bool | None = None
    follow: bool | None = None
    favourite: bool | None = None
    reblog: bool | None = None
    poll: bool | None = None


class DataParam(BaseModel):
    alerts: AlertsParam | None = None
    policy: str | None = None


class CreatePushRequest(BaseModel):
    subscription: SubscriptionParam
    data: DataParam | None = None


class UpdatePushRequest(BaseModel):
    data: DataParam


def _get_session_id(request: Request) -> str:
    """Cookie または OAuth トークンからセッション ID を取得する。"""
    session_id = request.cookies.get("nekonoverse_session")
    if session_id:
        return session_id
    # OAuthトークンの場合、Authorization headerをセッションIDとして使用
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return f"oauth:{auth_header[7:]}"
    raise HTTPException(status_code=401, detail="No session")


def _subscription_response(sub) -> dict:
    return {
        "id": str(sub.id),
        "endpoint": sub.endpoint,
        "alerts": sub.alerts,
        "policy": sub.policy,
        "server_key": get_vapid_public_key_base64url(),
    }


@router.post("/subscription")
async def create_push_subscription(
    body: CreatePushRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = _get_session_id(request)
    alerts = None
    policy = "all"
    if body.data:
        if body.data.alerts:
            alerts = {k: v for k, v in body.data.alerts.model_dump().items() if v is not None}
        if body.data.policy:
            policy = body.data.policy

    sub = await create_subscription(
        db=db,
        actor_id=user.actor_id,
        session_id=session_id,
        endpoint=body.subscription.endpoint,
        key_p256dh=body.subscription.keys.p256dh,
        key_auth=body.subscription.keys.auth,
        alerts=alerts,
        policy=policy,
    )
    await db.commit()
    return _subscription_response(sub)


@router.get("/subscription")
async def get_push_subscription(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = _get_session_id(request)
    sub = await get_subscription_by_session(db, session_id)
    if not sub:
        raise HTTPException(status_code=404, detail="No push subscription")
    return _subscription_response(sub)


@router.put("/subscription")
async def update_push_subscription(
    body: UpdatePushRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = _get_session_id(request)
    alerts = None
    policy = None
    if body.data.alerts:
        alerts = {k: v for k, v in body.data.alerts.model_dump().items() if v is not None}
    if body.data.policy:
        policy = body.data.policy

    sub = await update_subscription_alerts(db, session_id, alerts=alerts, policy=policy)
    if not sub:
        raise HTTPException(status_code=404, detail="No push subscription")
    await db.commit()
    return _subscription_response(sub)


@router.delete("/subscription")
async def delete_push_subscription(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    session_id = _get_session_id(request)
    deleted = await delete_subscription(db, session_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="No push subscription")
    await db.commit()
    return {}
