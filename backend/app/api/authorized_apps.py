"""認可済みアプリケーション管理エンドポイント。"""

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.oauth import OAuthApplication, OAuthToken
from app.models.user import User

router = APIRouter(prefix="/api/v1/authorized_apps", tags=["authorized_apps"])


@router.get("")
async def list_authorized_apps(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    # このユーザーの有効なトークンを持つアプリを検索
    stmt = (
        select(
            OAuthApplication.id,
            OAuthApplication.name,
            OAuthApplication.website,
            OAuthApplication.scopes,
            func.min(OAuthToken.created_at).label("first_authorized_at"),
        )
        .join(OAuthToken, OAuthToken.application_id == OAuthApplication.id)
        .where(
            OAuthToken.user_id == user.id,
            OAuthToken.revoked_at.is_(None),
            or_(OAuthToken.expires_at.is_(None), OAuthToken.expires_at > now),
        )
        .group_by(OAuthApplication.id)
        .order_by(func.min(OAuthToken.created_at).desc())
    )
    result = await db.execute(stmt)
    rows = result.all()

    from app.api.mastodon.statuses import _to_mastodon_datetime

    return [
        {
            "id": str(row.id),
            "name": row.name,
            "website": row.website,
            "scopes": row.scopes.split() if row.scopes else [],
            "created_at": _to_mastodon_datetime(row.first_authorized_at),
        }
        for row in rows
    ]


@router.delete("/{app_id}")
async def revoke_authorized_app(
    app_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(OAuthToken).where(
            OAuthToken.application_id == app_id,
            OAuthToken.user_id == user.id,
            OAuthToken.revoked_at.is_(None),
        )
    )
    tokens = result.scalars().all()
    if not tokens:
        raise HTTPException(status_code=404, detail="No active authorization found")

    for token in tokens:
        token.revoked_at = now

    await db.commit()
    return {}
