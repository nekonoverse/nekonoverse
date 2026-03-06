"""Admin and moderation API endpoints."""

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_admin_user, get_current_user, get_db, get_staff_user
from app.models.actor import Actor
from app.models.moderation_log import ModerationLog
from app.models.note import Note
from app.models.user import User
from app.schemas.admin import (
    AdminStatsResponse,
    AdminUserResponse,
    DomainBlockRequest,
    DomainBlockResponse,
    ModerationActionRequest,
    ModerationLogResponse,
    ReportResponse,
    RoleChangeRequest,
    ServerSettingsResponse,
    ServerSettingsUpdate,
)

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


# --- Server Icon (existing) ---


@router.post("/server-icon")
async def upload_server_icon(
    file: UploadFile = File(...),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.drive_service import file_to_url, upload_drive_file

    data = await file.read()
    try:
        drive_file = await upload_drive_file(
            db=db, owner=None, data=data,
            filename=file.filename or "server-icon",
            mime_type=file.content_type or "image/png",
            server_file=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    url = file_to_url(drive_file)

    from app.valkey_client import valkey
    await valkey.set("server:icon_url", url)

    return {"ok": True, "url": url}


# --- Server Settings ---


@router.get("/settings", response_model=ServerSettingsResponse)
async def get_server_settings(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.server_settings_service import get_all_settings

    settings = await get_all_settings(db)
    return ServerSettingsResponse(
        server_name=settings.get("server_name"),
        server_description=settings.get("server_description"),
        tos_url=settings.get("tos_url"),
        registration_open=settings.get("registration_open", "true") == "true",
    )


@router.patch("/settings", response_model=ServerSettingsResponse)
async def update_server_settings(
    body: ServerSettingsUpdate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import log_action
    from app.services.server_settings_service import get_all_settings, set_setting

    updates = body.model_dump(exclude_unset=True)
    for key, value in updates.items():
        if key == "registration_open":
            await set_setting(db, key, "true" if value else "false")
        else:
            await set_setting(db, key, value)
    await db.commit()

    await log_action(db, user, "update_settings", "server", "settings")
    await db.commit()

    settings = await get_all_settings(db)
    return ServerSettingsResponse(
        server_name=settings.get("server_name"),
        server_description=settings.get("server_description"),
        tos_url=settings.get("tos_url"),
        registration_open=settings.get("registration_open", "true") == "true",
    )


# --- Stats ---


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    note_count = (await db.execute(
        select(func.count(Note.id)).where(Note.deleted_at.is_(None))
    )).scalar() or 0
    domain_count = (await db.execute(
        select(func.count(func.distinct(Actor.domain))).where(Actor.domain.isnot(None))
    )).scalar() or 0
    return AdminStatsResponse(
        user_count=user_count,
        note_count=note_count,
        domain_count=domain_count,
    )


# --- User Management ---


@router.get("/users", response_model=list[AdminUserResponse])
async def list_users(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=100),
    offset: int = Query(default=0, ge=0),
):
    result = await db.execute(
        select(User)
        .options(selectinload(User.actor))
        .order_by(User.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    users = result.scalars().all()
    return [
        AdminUserResponse(
            id=u.id,
            username=u.actor.username,
            email=u.email,
            display_name=u.actor.display_name,
            role=u.role,
            is_active=u.is_active,
            suspended=u.actor.is_suspended,
            silenced=u.actor.is_silenced,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.patch("/users/{user_id}/role")
async def change_user_role(
    user_id: uuid.UUID,
    body: RoleChangeRequest,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import log_action

    target = await _get_user(db, user_id)
    if target.id == user.id:
        raise HTTPException(status_code=422, detail="Cannot change own role")

    old_role = target.role
    target.role = body.role
    await log_action(db, user, "role_change", "actor", str(target.actor_id),
                     f"{old_role} -> {body.role}")
    await db.commit()
    return {"ok": True, "role": body.role}


@router.post("/users/{user_id}/suspend")
async def suspend_user(
    user_id: uuid.UUID,
    body: ModerationActionRequest = ModerationActionRequest(),
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import suspend_actor

    target = await _get_user(db, user_id)
    if target.actor.is_suspended:
        raise HTTPException(status_code=422, detail="Already suspended")
    if target.id == user.id:
        raise HTTPException(status_code=422, detail="Cannot suspend self")

    await suspend_actor(db, target.actor, user, body.reason)
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/unsuspend")
async def unsuspend_user(
    user_id: uuid.UUID,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import unsuspend_actor

    target = await _get_user(db, user_id)
    if not target.actor.is_suspended:
        raise HTTPException(status_code=422, detail="Not suspended")

    await unsuspend_actor(db, target.actor, user)
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/silence")
async def silence_user(
    user_id: uuid.UUID,
    body: ModerationActionRequest = ModerationActionRequest(),
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import silence_actor

    target = await _get_user(db, user_id)
    if target.actor.is_silenced:
        raise HTTPException(status_code=422, detail="Already silenced")

    await silence_actor(db, target.actor, user, body.reason)
    await db.commit()
    return {"ok": True}


@router.post("/users/{user_id}/unsilence")
async def unsilence_user(
    user_id: uuid.UUID,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import unsilence_actor

    target = await _get_user(db, user_id)
    if not target.actor.is_silenced:
        raise HTTPException(status_code=422, detail="Not silenced")

    await unsilence_actor(db, target.actor, user)
    await db.commit()
    return {"ok": True}


# --- Domain Blocks ---


@router.get("/domain_blocks", response_model=list[DomainBlockResponse])
async def list_domain_blocks(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.domain_block_service import list_domain_blocks as _list

    blocks = await _list(db)
    return [DomainBlockResponse.model_validate(b) for b in blocks]


@router.post("/domain_blocks", response_model=DomainBlockResponse, status_code=201)
async def create_domain_block(
    body: DomainBlockRequest,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.domain_block_service import create_domain_block as _create
    from app.services.moderation_service import log_action

    try:
        block = await _create(db, body.domain, body.severity, body.reason, user)
    except Exception:
        raise HTTPException(status_code=422, detail="Domain already blocked")

    await log_action(db, user, "domain_block", "domain", body.domain, body.reason)
    await db.commit()
    return DomainBlockResponse.model_validate(block)


@router.delete("/domain_blocks/{domain}")
async def remove_domain_block(
    domain: str,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.domain_block_service import remove_domain_block as _remove
    from app.services.moderation_service import log_action

    removed = await _remove(db, domain)
    if not removed:
        raise HTTPException(status_code=404, detail="Domain block not found")

    await log_action(db, user, "domain_unblock", "domain", domain)
    await db.commit()
    return {"ok": True}


# --- Reports ---


@router.get("/reports", response_model=list[ReportResponse])
async def get_reports(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
    status: str | None = Query(default=None),
):
    from app.services.report_service import list_reports

    reports = await list_reports(db, status)
    return [
        ReportResponse(
            id=r.id,
            reporter=r.reporter_actor.username + ("@" + r.reporter_actor.domain if r.reporter_actor.domain else ""),
            target=r.target_actor.username + ("@" + r.target_actor.domain if r.target_actor.domain else ""),
            target_note_id=r.target_note_id,
            comment=r.comment,
            status=r.status,
            created_at=r.created_at,
            resolved_at=r.resolved_at,
        )
        for r in reports
    ]


@router.post("/reports/{report_id}/resolve")
async def resolve_report(
    report_id: uuid.UUID,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import log_action
    from app.services.report_service import get_report_by_id, resolve_report as _resolve

    report = await get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "open":
        raise HTTPException(status_code=422, detail="Report already handled")

    await _resolve(db, report, user)
    await log_action(db, user, "resolve_report", "report", str(report_id))
    await db.commit()
    return {"ok": True}


@router.post("/reports/{report_id}/reject")
async def reject_report(
    report_id: uuid.UUID,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import log_action
    from app.services.report_service import get_report_by_id, reject_report as _reject

    report = await get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    if report.status != "open":
        raise HTTPException(status_code=422, detail="Report already handled")

    await _reject(db, report, user)
    await log_action(db, user, "reject_report", "report", str(report_id))
    await db.commit()
    return {"ok": True}


# --- Post Moderation ---


@router.delete("/notes/{note_id}")
async def admin_delete_note(
    note_id: uuid.UUID,
    body: ModerationActionRequest = ModerationActionRequest(),
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import admin_delete_note as _delete
    from app.services.note_service import get_note_by_id

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    await _delete(db, note, user, body.reason)
    await db.commit()
    return {"ok": True}


@router.post("/notes/{note_id}/sensitive")
async def force_note_sensitive(
    note_id: uuid.UUID,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.moderation_service import force_sensitive
    from app.services.note_service import get_note_by_id

    note = await get_note_by_id(db, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")

    await force_sensitive(db, note, user)
    await db.commit()
    return {"ok": True}


# --- Moderation Log ---


@router.get("/log", response_model=list[ModerationLogResponse])
async def get_moderation_log(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=50, le=100),
):
    result = await db.execute(
        select(ModerationLog)
        .options(selectinload(ModerationLog.moderator).selectinload(User.actor))
        .order_by(ModerationLog.created_at.desc())
        .limit(limit)
    )
    entries = result.scalars().all()
    return [
        ModerationLogResponse(
            id=e.id,
            moderator=e.moderator.actor.username if e.moderator and e.moderator.actor else "unknown",
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            reason=e.reason,
            created_at=e.created_at,
        )
        for e in entries
    ]


# --- Helpers ---


async def _get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User).options(selectinload(User.actor)).where(User.id == user_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return target
