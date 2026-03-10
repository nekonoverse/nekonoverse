"""Invitation code service."""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invitation_code import InvitationCode
from app.models.user import User


async def create_invitation(
    db: AsyncSession,
    creator: User,
    *,
    max_uses: int | None = 1,
    expires_in_days: int | None = None,
) -> InvitationCode:
    """Create a new invitation code with optional usage limit and expiration."""
    code = uuid.uuid4().hex
    expires_at = None
    if expires_in_days is not None and expires_in_days > 0:
        expires_at = datetime.now(timezone.utc) + timedelta(days=expires_in_days)

    invite = InvitationCode(
        code=code,
        created_by_id=creator.id,
        max_uses=max_uses,
        expires_at=expires_at,
    )
    db.add(invite)
    await db.flush()
    return invite


async def list_invitations(db: AsyncSession, user: User) -> list[InvitationCode]:
    """List invitation codes created by a user."""
    result = await db.execute(
        select(InvitationCode)
        .where(InvitationCode.created_by_id == user.id)
        .options(selectinload(InvitationCode.used_by).selectinload(User.actor))
        .order_by(InvitationCode.created_at.desc())
    )
    return list(result.scalars().all())


async def validate_invitation_code(db: AsyncSession, code: str) -> InvitationCode | None:
    """Return the invitation if valid (exists, not exhausted, not expired), else None."""
    result = await db.execute(select(InvitationCode).where(InvitationCode.code == code))
    invite = result.scalar_one_or_none()
    if invite is None:
        return None
    # 使用回数上限チェック (max_uses=null は無制限)
    if invite.max_uses is not None and invite.use_count >= invite.max_uses:
        return None
    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        return None
    return invite


async def redeem_invitation(db: AsyncSession, invite: InvitationCode, user: User) -> None:
    """Mark an invitation code as used (increment use_count)."""
    invite.use_count += 1
    invite.used_by_id = user.id
    invite.used_at = datetime.now(timezone.utc)
    await db.flush()


async def delete_invitation(db: AsyncSession, code: str, user: User) -> bool:
    """Delete an invitation code. Only the creator or an admin can delete."""
    result = await db.execute(select(InvitationCode).where(InvitationCode.code == code))
    invite = result.scalar_one_or_none()
    if invite is None:
        return False
    if invite.created_by_id != user.id and not user.is_admin:
        return False
    await db.delete(invite)
    await db.flush()
    return True
