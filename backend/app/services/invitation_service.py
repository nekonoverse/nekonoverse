"""Invitation code service."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.invitation_code import InvitationCode
from app.models.user import User


async def create_invitation(db: AsyncSession, creator: User) -> InvitationCode:
    """Create a new single-use invitation code."""
    code = uuid.uuid4().hex
    invite = InvitationCode(code=code, created_by_id=creator.id)
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
    """Return the invitation if valid (exists, unused, not expired), else None."""
    result = await db.execute(
        select(InvitationCode).where(InvitationCode.code == code)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        return None
    if invite.used_by_id is not None:
        return None
    if invite.expires_at and invite.expires_at < datetime.now(timezone.utc):
        return None
    return invite


async def redeem_invitation(
    db: AsyncSession, invite: InvitationCode, user: User
) -> None:
    """Mark an invitation code as used."""
    invite.used_by_id = user.id
    invite.used_at = datetime.now(timezone.utc)
    await db.flush()


async def delete_invitation(db: AsyncSession, code: str, user: User) -> bool:
    """Delete an invitation code. Only the creator or an admin can delete."""
    result = await db.execute(
        select(InvitationCode).where(InvitationCode.code == code)
    )
    invite = result.scalar_one_or_none()
    if invite is None:
        return False
    if invite.created_by_id != user.id and not user.is_admin:
        return False
    await db.delete(invite)
    await db.flush()
    return True
