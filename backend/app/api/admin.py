"""Admin and moderation API endpoints."""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from sqlalchemy import func, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.dependencies import get_admin_user, get_db, get_staff_user
from app.models.actor import Actor
from app.models.delivery import DeliveryJob
from app.models.follow import Follow
from app.models.moderation_log import ModerationLog
from app.models.note import Note
from app.models.user import User
from app.schemas.admin import (
    AdminEmojiResponse,
    AdminEmojiUpdate,
    AdminRemoteEmojiResponse,
    AdminStatsResponse,
    AdminUserResponse,
    DomainBlockRequest,
    DomainBlockResponse,
    FederatedServerDetailResponse,
    FederatedServerListResponse,
    FederatedServerResponse,
    ImportByShortcodeRequest,
    ModerationActionRequest,
    ModerationLogResponse,
    PendingRegistrationResponse,
    QueueJobListResponse,
    QueueJobResponse,
    QueueStatsResponse,
    ReportResponse,
    RoleChangeRequest,
    ServerSettingsResponse,
    ServerSettingsUpdate,
    SystemStatsResponse,
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
            db=db,
            owner=None,
            data=data,
            filename=file.filename or "server-icon",
            mime_type=file.content_type or "image/png",
            server_file=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    url = file_to_url(drive_file)

    from app.services.server_settings_service import set_setting

    await set_setting(db, "server_icon_url", url)
    await db.commit()

    return {"ok": True, "url": url}


# --- Server Settings ---


@router.get("/settings", response_model=ServerSettingsResponse)
async def get_server_settings(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.server_settings_service import get_all_settings

    settings = await get_all_settings(db)
    mode = settings.get("registration_mode")
    if mode is None:
        reg_open = settings.get("registration_open", "true") == "true"
        mode = "open" if reg_open else "closed"
    return ServerSettingsResponse(
        server_name=settings.get("server_name"),
        server_description=settings.get("server_description"),
        tos_url=settings.get("tos_url"),
        registration_open=mode != "closed",
        registration_mode=mode,
        invite_create_role=settings.get("invite_create_role", "admin"),
        server_icon_url=settings.get("server_icon_url"),
        server_theme_color=settings.get("server_theme_color"),
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
        elif key == "registration_mode":
            await set_setting(db, key, value)
            # Sync legacy registration_open for backward compat
            await set_setting(db, "registration_open", "true" if value != "closed" else "false")
            # 承認制から別モードへ変更時: pendingユーザーを自動処理
            if value != "approval":
                await _resolve_pending_users(db, user, value)
        elif key == "invite_create_role":
            await set_setting(db, key, value)
        else:
            await set_setting(db, key, value)
    await db.commit()

    await log_action(db, user, "update_settings", "server", "settings")
    await db.commit()

    settings = await get_all_settings(db)
    mode = settings.get("registration_mode")
    if mode is None:
        reg_open = settings.get("registration_open", "true") == "true"
        mode = "open" if reg_open else "closed"
    return ServerSettingsResponse(
        server_name=settings.get("server_name"),
        server_description=settings.get("server_description"),
        tos_url=settings.get("tos_url"),
        registration_open=mode != "closed",
        registration_mode=mode,
        invite_create_role=settings.get("invite_create_role", "admin"),
        server_icon_url=settings.get("server_icon_url"),
        server_theme_color=settings.get("server_theme_color"),
    )


# --- Stats ---


@router.get("/stats", response_model=AdminStatsResponse)
async def get_admin_stats(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    user_count = (await db.execute(select(func.count(User.id)))).scalar() or 0
    # ローカルユーザーの投稿のみカウント
    note_count = (
        await db.execute(
            select(func.count(Note.id)).where(
                Note.deleted_at.is_(None),
                Note.local.is_(True),
            )
        )
    ).scalar() or 0
    # 配送中/購読中のアクティブな連合ドメインのみカウント
    # 配送先ドメイン（delivered/pending/processing）
    delivery_domains = select(
        func.substring(DeliveryJob.target_inbox_url, r"https?://([^/]+)").label("domain")
    ).where(DeliveryJob.status.in_(["delivered", "pending", "processing"]))
    # フォロー関係のあるリモートドメイン（ローカル→リモート、リモート→ローカル）
    local_actor_ids = select(Actor.id).where(Actor.domain.is_(None))
    # ローカルユーザーがフォローしているリモートActorのドメイン
    following_domains = (
        select(Actor.domain.label("domain"))
        .join(Follow, Follow.following_id == Actor.id)
        .where(Follow.follower_id.in_(local_actor_ids), Actor.domain.isnot(None))
    )
    # リモートActorがローカルユーザーをフォローしているドメイン
    follower_domains = (
        select(Actor.domain.label("domain"))
        .join(Follow, Follow.follower_id == Actor.id)
        .where(Follow.following_id.in_(local_actor_ids), Actor.domain.isnot(None))
    )
    active_domains = union(delivery_domains, following_domains, follower_domains).subquery()
    domain_count = (
        await db.execute(select(func.count(func.distinct(active_domains.c.domain))))
    ).scalar() or 0
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
    await log_action(
        db, user, "role_change", "actor", str(target.actor_id), f"{old_role} -> {body.role}"
    )
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
    _check_moderation_permission(user, target)

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
    _check_moderation_permission(user, target)

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
    if target.id == user.id:
        raise HTTPException(status_code=422, detail="Cannot silence self")
    _check_moderation_permission(user, target)

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
    _check_moderation_permission(user, target)

    await unsilence_actor(db, target.actor, user)
    await db.commit()
    return {"ok": True}


# --- Federation ---


@router.get("/federation", response_model=FederatedServerListResponse)
async def list_federated_servers(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=40, le=200, ge=1),
    offset: int = Query(default=0, ge=0),
    sort: str = Query(
        default="user_count",
        pattern=r"^(domain|user_count|note_count|last_activity)$",
    ),
    order: str = Query(default="desc", pattern=r"^(asc|desc)$"),
    search: str | None = Query(default=None, max_length=255),
    status: str | None = Query(default=None, pattern=r"^(all|active|suspended|silenced)$"),
):
    from app.services.federation_service import get_federated_servers

    effective_status = None if status in (None, "all") else status
    servers, total = await get_federated_servers(
        db,
        limit=limit,
        offset=offset,
        sort=sort,
        order=order,
        search=search,
        status=effective_status,
    )
    return FederatedServerListResponse(
        servers=[FederatedServerResponse(**s) for s in servers],
        total=total,
    )


@router.get("/federation/{domain:path}", response_model=FederatedServerDetailResponse)
async def get_federated_server_detail_endpoint(
    domain: str,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.federation_service import get_federated_server_detail

    detail = await get_federated_server_detail(db, domain)
    if not detail:
        raise HTTPException(status_code=404, detail="Server not found")
    return FederatedServerDetailResponse(**detail)


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
            reporter=r.reporter_actor.username
            + ("@" + r.reporter_actor.domain if r.reporter_actor.domain else ""),
            target=r.target_actor.username
            + ("@" + r.target_actor.domain if r.target_actor.domain else ""),
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
    from app.services.report_service import get_report_by_id
    from app.services.report_service import resolve_report as _resolve

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
    from app.services.report_service import get_report_by_id
    from app.services.report_service import reject_report as _reject

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
    if note.actor and note.actor.local_user:
        _check_moderation_permission(user, note.actor.local_user)

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
    if note.actor and note.actor.local_user:
        _check_moderation_permission(user, note.actor.local_user)

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
            moderator=(
                e.moderator.actor.username if e.moderator and e.moderator.actor else "unknown"
            ),
            action=e.action,
            target_type=e.target_type,
            target_id=e.target_id,
            reason=e.reason,
            created_at=e.created_at,
        )
        for e in entries
    ]


# --- Custom Emoji Management ---


@router.get("/emoji/list", response_model=list[AdminEmojiResponse])
async def list_emojis(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.emoji_service import list_all_local_emojis

    emojis = await list_all_local_emojis(db)
    return [AdminEmojiResponse.model_validate(e) for e in emojis]


@router.get("/emoji/remote", response_model=list[AdminRemoteEmojiResponse])
async def list_remote_emojis_endpoint(
    domain: str | None = Query(None),
    search: str | None = Query(None),
    limit: int = Query(100, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.emoji_service import list_remote_emojis

    emojis = await list_remote_emojis(db, domain=domain, search=search, limit=limit, offset=offset)
    return [AdminRemoteEmojiResponse.model_validate(e) for e in emojis]


@router.get("/emoji/remote/domains")
async def list_remote_emoji_domains_endpoint(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.emoji_service import list_remote_emoji_domains

    return await list_remote_emoji_domains(db)


@router.post("/emoji/import-remote/{emoji_id}", response_model=AdminEmojiResponse)
async def import_remote_emoji(
    emoji_id: uuid.UUID,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.emoji_service import import_remote_emoji_to_local

    try:
        emoji = await import_remote_emoji_to_local(db, emoji_id)
        await db.commit()
        return AdminEmojiResponse.model_validate(emoji)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/emoji/import-by-shortcode", response_model=AdminEmojiResponse)
async def import_remote_emoji_by_shortcode(
    body: ImportByShortcodeRequest,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.emoji_service import get_custom_emoji, import_remote_emoji_to_local

    remote = await get_custom_emoji(db, body.shortcode, body.domain)
    if not remote:
        raise HTTPException(status_code=404, detail="Remote emoji not found")
    try:
        emoji = await import_remote_emoji_to_local(db, remote.id)
        await db.commit()
        return AdminEmojiResponse.model_validate(emoji)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/emoji/add", response_model=AdminEmojiResponse)
async def add_emoji(
    file: UploadFile = File(...),
    shortcode: str = Form(...),
    category: str | None = Form(None),
    aliases: str | None = Form(None),
    license: str | None = Form(None),
    is_sensitive: bool = Form(False),
    local_only: bool = Form(False),
    author: str | None = Form(None),
    description: str | None = Form(None),
    copy_permission: str | None = Form(None),
    usage_info: str | None = Form(None),
    is_based_on: str | None = Form(None),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    import json as json_mod

    from app.services.drive_service import file_to_url, upload_drive_file
    from app.services.emoji_service import create_local_emoji, get_custom_emoji

    existing = await get_custom_emoji(db, shortcode, None)
    if existing:
        raise HTTPException(status_code=409, detail="Shortcode already exists")

    data = await file.read()
    try:
        drive_file = await upload_drive_file(
            db=db,
            owner=None,
            data=data,
            filename=f"emoji_{shortcode}",
            mime_type=file.content_type or "image/png",
            server_file=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    url = file_to_url(drive_file)
    parsed_aliases = json_mod.loads(aliases) if aliases else None

    emoji = await create_local_emoji(
        db,
        shortcode=shortcode,
        url=url,
        drive_file_id=drive_file.id,
        category=category,
        aliases=parsed_aliases,
        license=license,
        is_sensitive=is_sensitive,
        local_only=local_only,
        author=author,
        description=description,
        copy_permission=copy_permission,
        usage_info=usage_info,
        is_based_on=is_based_on,
    )
    await db.commit()
    return AdminEmojiResponse.model_validate(emoji)


@router.patch("/emoji/{emoji_id}", response_model=AdminEmojiResponse)
async def update_emoji_endpoint(
    emoji_id: uuid.UUID,
    body: AdminEmojiUpdate,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.emoji_service import update_emoji

    updates = body.model_dump(exclude_unset=True)
    emoji = await update_emoji(db, emoji_id, updates)
    if not emoji:
        raise HTTPException(status_code=404, detail="Emoji not found")
    await db.commit()
    return AdminEmojiResponse.model_validate(emoji)


@router.delete("/emoji/{emoji_id}")
async def delete_emoji_endpoint(
    emoji_id: uuid.UUID,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.emoji_service import delete_emoji, get_emoji_by_id

    emoji = await get_emoji_by_id(db, emoji_id)
    if not emoji:
        raise HTTPException(status_code=404, detail="Emoji not found")

    if emoji.drive_file_id:
        from app.services.drive_service import delete_drive_file, get_drive_file

        df = await get_drive_file(db, emoji.drive_file_id)
        if df:
            await delete_drive_file(db, df)

    await delete_emoji(db, emoji_id)
    await db.commit()
    return {"ok": True}


@router.get("/emoji/export")
async def export_emojis(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    import io
    import json as json_mod
    import zipfile
    from datetime import datetime, timezone

    from fastapi.responses import StreamingResponse

    from app.config import settings as app_settings
    from app.services.emoji_service import list_all_local_emojis
    from app.storage import get_file_stream

    emojis = await list_all_local_emojis(db)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        meta_emojis = []
        for e in emojis:
            ext = e.url.rsplit(".", 1)[-1] if "." in e.url else "png"
            filename = f"{e.shortcode}.{ext}"

            # Read image from S3 via drive file s3_key
            image_data = None
            if e.drive_file_id:
                from app.services.drive_service import get_drive_file

                df = await get_drive_file(db, e.drive_file_id)
                if df:
                    try:
                        aiter, _ct, _sz = await get_file_stream(df.s3_key)
                        chunks = []
                        async for chunk in aiter:
                            chunks.append(chunk)
                        image_data = b"".join(chunks)
                    except Exception:
                        pass

            if image_data:
                zf.writestr(filename, image_data)
            else:
                continue

            meta_emojis.append(
                {
                    "downloaded": True,
                    "fileName": filename,
                    "emoji": {
                        "name": e.shortcode,
                        "category": e.category,
                        "aliases": e.aliases or [],
                        "license": e.license,
                        "isSensitive": e.is_sensitive,
                        "localOnly": e.local_only,
                        "author": e.author,
                        "description": e.description,
                        "copyPermission": e.copy_permission,
                        "usageInfo": e.usage_info,
                        "isBasedOn": e.is_based_on,
                    },
                }
            )

        meta = {
            "metaVersion": 2,
            "host": app_settings.domain,
            "exportedAt": datetime.now(timezone.utc).isoformat(),
            "emojis": meta_emojis,
        }
        zf.writestr("meta.json", json_mod.dumps(meta, ensure_ascii=False, indent=2))

    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=emojis-{app_settings.domain}.zip"},
    )


@router.post("/emoji/import")
async def import_emojis(
    file: UploadFile = File(...),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    import io
    import json as json_mod
    import zipfile

    from app.services.drive_service import file_to_url, upload_drive_file
    from app.services.emoji_service import create_local_emoji, get_custom_emoji

    data = await file.read()
    buf = io.BytesIO(data)

    if not zipfile.is_zipfile(buf):
        raise HTTPException(status_code=422, detail="Invalid ZIP file")

    buf.seek(0)
    results: dict = {"imported": 0, "skipped": 0, "errors": []}

    with zipfile.ZipFile(buf, "r") as zf:
        if "meta.json" not in zf.namelist():
            raise HTTPException(status_code=422, detail="meta.json not found in ZIP")

        meta = json_mod.loads(zf.read("meta.json"))
        import_host = meta.get("host")

        for entry in meta.get("emojis", []):
            if not entry.get("downloaded", False):
                results["skipped"] += 1
                continue

            emoji_data = entry.get("emoji", {})
            shortcode = emoji_data.get("name")
            filename = entry.get("fileName")

            if not shortcode or not filename:
                results["errors"].append("Missing name or fileName")
                continue

            existing = await get_custom_emoji(db, shortcode, None)
            if existing:
                results["skipped"] += 1
                continue

            try:
                image_data = zf.read(filename)
            except KeyError:
                results["errors"].append(f"File {filename} not found in ZIP")
                continue

            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "png"
            mime_map = {
                "png": "image/png",
                "jpg": "image/jpeg",
                "jpeg": "image/jpeg",
                "gif": "image/gif",
                "webp": "image/webp",
                "avif": "image/avif",
            }
            mime_type = mime_map.get(ext, "image/png")

            try:
                drive_file = await upload_drive_file(
                    db=db,
                    owner=None,
                    data=image_data,
                    filename=f"emoji_{shortcode}",
                    mime_type=mime_type,
                    server_file=True,
                )
                url = file_to_url(drive_file)

                await create_local_emoji(
                    db,
                    shortcode=shortcode,
                    url=url,
                    drive_file_id=drive_file.id,
                    category=emoji_data.get("category"),
                    aliases=emoji_data.get("aliases"),
                    license=emoji_data.get("license"),
                    is_sensitive=emoji_data.get("isSensitive", False),
                    local_only=emoji_data.get("localOnly", False),
                    author=emoji_data.get("author"),
                    description=emoji_data.get("description"),
                    copy_permission=emoji_data.get("copyPermission"),
                    usage_info=emoji_data.get("usageInfo"),
                    is_based_on=emoji_data.get("isBasedOn"),
                    import_from=import_host,
                )
                results["imported"] += 1
            except Exception as e:
                results["errors"].append(f"{shortcode}: {str(e)}")

    await db.commit()
    return results


# --- Server Files ---


@router.get("/server-files")
async def list_server_files(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.drive_file import DriveFile
    from app.services.drive_service import file_to_url

    result = await db.execute(
        select(DriveFile)
        .where(DriveFile.server_file.is_(True))
        .order_by(DriveFile.created_at.desc())
    )
    files = result.scalars().all()
    return [
        {
            "id": str(f.id),
            "filename": f.filename,
            "mime_type": f.mime_type,
            "size_bytes": f.size_bytes,
            "url": file_to_url(f),
            "created_at": f.created_at.isoformat(),
        }
        for f in files
    ]


@router.post("/server-files")
async def upload_server_file(
    file: UploadFile = File(...),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.drive_service import file_to_url, upload_drive_file

    data = await file.read()
    try:
        drive_file = await upload_drive_file(
            db=db,
            owner=None,
            data=data,
            filename=file.filename or "server-file",
            mime_type=file.content_type or "application/octet-stream",
            server_file=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    await db.commit()
    return {
        "id": str(drive_file.id),
        "filename": drive_file.filename,
        "mime_type": drive_file.mime_type,
        "size_bytes": drive_file.size_bytes,
        "url": file_to_url(drive_file),
        "created_at": drive_file.created_at.isoformat(),
    }


@router.delete("/server-files/{file_id}")
async def delete_server_file_endpoint(
    file_id: uuid.UUID,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.drive_service import delete_drive_file, get_drive_file

    drive_file = await get_drive_file(db, file_id)
    if not drive_file or not drive_file.server_file:
        raise HTTPException(status_code=404, detail="Server file not found")

    await delete_drive_file(db, drive_file)
    await db.commit()
    return {"ok": True}


# --- Queue Management ---


@router.get("/queue/stats", response_model=QueueStatsResponse)
async def get_queue_stats(
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.queue_service import get_queue_stats

    return await get_queue_stats(db)


@router.get("/queue/jobs", response_model=QueueJobListResponse)
async def list_queue_jobs(
    status: str | None = Query(None),
    domain: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.queue_service import get_queue_jobs

    jobs, total = await get_queue_jobs(db, status, domain, limit, offset)
    return QueueJobListResponse(
        jobs=[QueueJobResponse.model_validate(j) for j in jobs],
        total=total,
    )


@router.post("/queue/retry/{job_id}")
async def retry_queue_job(
    job_id: uuid.UUID,
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.queue_service import retry_job

    success = await retry_job(db, job_id)
    if not success:
        raise HTTPException(status_code=404, detail="Job not found or not dead")
    return {"ok": True}


@router.post("/queue/retry-all")
async def retry_all_dead_jobs(
    domain: str | None = Query(None),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.queue_service import retry_all_dead

    count = await retry_all_dead(db, domain)
    return {"ok": True, "retried": count}


@router.delete("/queue/purge")
async def purge_delivered_jobs(
    older_than_hours: int = Query(24, ge=1),
    user: User = Depends(get_admin_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services.queue_service import purge_delivered

    count = await purge_delivered(db, older_than_hours)
    return {"ok": True, "purged": count}


# --- System Stats ---


@router.get("/system/stats", response_model=SystemStatsResponse)
async def get_system_stats(
    user: User = Depends(get_admin_user),
):
    from app.database import engine
    from app.valkey_client import valkey

    data: dict = {}

    # DB pool stats
    pool = engine.pool
    data["db_pool_size"] = pool.size()
    data["db_pool_checked_in"] = pool.checkedin()
    data["db_pool_checked_out"] = pool.checkedout()
    data["db_pool_overflow"] = pool.overflow()

    # Valkey stats
    try:
        info = await valkey.info()
        data["valkey_connected_clients"] = info.get("connected_clients", 0)
        data["valkey_used_memory_human"] = info.get("used_memory_human", "")
        # キーの合計数
        total_keys = 0
        for key, val in info.items():
            if key.startswith("db") and isinstance(val, dict):
                total_keys += val.get("keys", 0)
        data["valkey_total_keys"] = total_keys
    except Exception:
        pass

    # System stats (/proc読み取り)
    try:
        with open("/proc/loadavg") as f:
            parts = f.read().split()
            data["load_avg_1m"] = float(parts[0])
            data["load_avg_5m"] = float(parts[1])
            data["load_avg_15m"] = float(parts[2])
    except Exception:
        pass

    try:
        with open("/proc/meminfo") as f:
            meminfo = {}
            for line in f:
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    meminfo[key] = int(val)
            total_kb = meminfo.get("MemTotal", 0)
            available_kb = meminfo.get("MemAvailable", 0)
            data["memory_total_mb"] = total_kb // 1024
            data["memory_available_mb"] = available_kb // 1024
            if total_kb > 0:
                data["memory_percent"] = round((1 - available_kb / total_kb) * 100, 1)
    except Exception:
        pass

    try:
        with open("/proc/uptime") as f:
            data["uptime_seconds"] = float(f.read().split()[0])
    except Exception:
        pass

    # Worker heartbeat
    try:
        heartbeat = await valkey.get("worker:heartbeat")
        if heartbeat:
            data["worker_alive"] = True
            data["worker_last_heartbeat"] = heartbeat
        else:
            data["worker_alive"] = False
    except Exception:
        pass

    return SystemStatsResponse(**data)


# --- Pending Registrations ---


@router.get("/registrations", response_model=list[PendingRegistrationResponse])
async def list_pending_registrations(
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """List users awaiting approval."""
    result = await db.execute(
        select(User)
        .options(selectinload(User.actor))
        .where(User.approval_status == "pending")
        .order_by(User.created_at.asc())
    )
    users = result.scalars().all()
    return [
        PendingRegistrationResponse(
            id=u.id,
            username=u.actor.username,
            email=u.email,
            reason=u.registration_reason,
            created_at=u.created_at,
        )
        for u in users
    ]


@router.post("/registrations/{user_id}/approve")
async def approve_registration(
    user_id: uuid.UUID,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Approve a pending registration."""
    from app.services.moderation_service import log_action

    target = await _get_user(db, user_id)
    if target.approval_status != "pending":
        raise HTTPException(status_code=422, detail="User is not pending approval")

    target.approval_status = "approved"
    await log_action(db, user, "approve_registration", "user", str(target.id))
    await db.commit()
    return {"ok": True}


@router.post("/registrations/{user_id}/reject")
async def reject_registration(
    user_id: uuid.UUID,
    user: User = Depends(get_staff_user),
    db: AsyncSession = Depends(get_db),
):
    """Reject a pending registration and delete the user."""
    from app.services.moderation_service import log_action

    target = await _get_user(db, user_id)
    if target.approval_status != "pending":
        raise HTTPException(status_code=422, detail="User is not pending approval")

    actor = target.actor
    await log_action(db, user, "reject_registration", "user", str(target.id))
    await db.delete(target)
    await db.delete(actor)
    await db.commit()
    return {"ok": True}


# --- Helpers ---


async def _resolve_pending_users(db: AsyncSession, admin: User, new_mode: str):
    """Auto-resolve pending users when leaving approval mode.

    open -> approve all, closed/invite -> reject (delete) all.
    """
    from app.services.moderation_service import log_action

    result = await db.execute(
        select(User).options(selectinload(User.actor)).where(User.approval_status == "pending")
    )
    pending_users = result.scalars().all()

    if new_mode == "open":
        # 公開モード: 全員承認
        for u in pending_users:
            u.approval_status = "approved"
            await log_action(db, admin, "approve_registration", "user", str(u.id))
    else:
        # 非公開/招待制: 全員却下(削除)
        for u in pending_users:
            await log_action(db, admin, "reject_registration", "user", str(u.id))
            await db.delete(u)
            await db.delete(u.actor)


def _check_moderation_permission(actor: User, target: User):
    """Prevent moderators from taking action against staff members."""
    if actor.is_admin:
        return
    if target.is_staff:
        raise HTTPException(
            status_code=403,
            detail="Moderators cannot take action against staff members",
        )


async def _get_user(db: AsyncSession, user_id: uuid.UUID) -> User:
    result = await db.execute(
        select(User).options(selectinload(User.actor)).where(User.id == user_id)
    )
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    return target
