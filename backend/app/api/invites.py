"""Invitation code API endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.invitation import InvitationCodeResponse
from app.services.invitation_service import (
    create_invitation,
    delete_invitation,
    list_invitations,
)

router = APIRouter(prefix="/api/v1/invites", tags=["invites"])


def _can_create_invites(user: User, required_role: str) -> bool:
    """Check if user meets the minimum role requirement for creating invites."""
    if required_role == "user":
        return True
    if required_role == "moderator":
        return user.is_staff
    return user.is_admin


def _invite_response(invite) -> InvitationCodeResponse:
    created_by_name = "unknown"
    if invite.created_by and invite.created_by.actor:
        created_by_name = invite.created_by.actor.username
    used_by_name = None
    if invite.used_by and invite.used_by.actor:
        used_by_name = invite.used_by.actor.username
    return InvitationCodeResponse(
        code=invite.code,
        created_by=created_by_name,
        used_by=used_by_name,
        used_at=invite.used_at,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@router.post("", response_model=InvitationCodeResponse, status_code=201)
async def create_invite(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.server_settings_service import get_setting

    role_setting = await get_setting(db, "invite_create_role")
    required_role = role_setting or "admin"

    if not _can_create_invites(user, required_role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    invite = await create_invitation(db, user)
    await db.commit()

    return InvitationCodeResponse(
        code=invite.code,
        created_by=user.actor.username,
        used_by=None,
        used_at=None,
        expires_at=invite.expires_at,
        created_at=invite.created_at,
    )


@router.get("", response_model=list[InvitationCodeResponse])
async def list_my_invites(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.server_settings_service import get_setting

    role_setting = await get_setting(db, "invite_create_role")
    required_role = role_setting or "admin"

    if not _can_create_invites(user, required_role):
        raise HTTPException(status_code=403, detail="Insufficient permissions")

    invites = await list_invitations(db, user)
    return [_invite_response(inv) for inv in invites]


@router.delete("/{code}")
async def revoke_invite(
    code: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_invitation(db, code, user)
    if not deleted:
        raise HTTPException(status_code=404, detail="Invite not found")
    await db.commit()
    return {"ok": True}
