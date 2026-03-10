"""Media upload/download and drive API."""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.drive_file import DriveFile
from app.models.user import User
from app.schemas.media import DriveFileResponse, MediaAttachment
from app.services.drive_service import (
    auto_detect_focal_point,
    delete_drive_file,
    file_to_url,
    get_drive_file,
    list_user_files,
    update_drive_file_meta,
    upload_drive_file,
)

router = APIRouter(tags=["media"])


def _parse_focus(focus: str | None) -> tuple[float | None, float | None]:
    """Parse 'x,y' focus string into (focal_x, focal_y), clamped to [-1, 1]."""
    if not focus:
        return None, None
    parts = focus.split(",")
    if len(parts) != 2:
        return None, None
    try:
        x = max(-1.0, min(1.0, float(parts[0])))
        y = max(-1.0, min(1.0, float(parts[1])))
        return x, y
    except ValueError:
        return None, None


def _to_media_attachment(f: DriveFile) -> MediaAttachment:
    url = file_to_url(f)
    meta = None
    if f.width and f.height:
        meta = {"original": {"width": f.width, "height": f.height}}
    if f.focal_x is not None and f.focal_y is not None:
        if meta is None:
            meta = {}
        meta["focus"] = {"x": f.focal_x, "y": f.focal_y}
    return MediaAttachment(
        id=str(f.id),
        type="image" if f.mime_type.startswith("image/") else "unknown",
        url=url,
        preview_url=url,
        description=f.description,
        blurhash=f.blurhash,
        meta=meta,
    )


def _to_drive_response(f: DriveFile) -> DriveFileResponse:
    return DriveFileResponse(
        id=f.id,
        filename=f.filename,
        mime_type=f.mime_type,
        size_bytes=f.size_bytes,
        url=file_to_url(f),
        width=f.width,
        height=f.height,
        description=f.description,
        blurhash=f.blurhash,
        focal_x=f.focal_x,
        focal_y=f.focal_y,
        server_file=f.server_file,
        created_at=f.created_at,
    )


@router.post("/api/v1/media", response_model=MediaAttachment)
async def upload_media_v1(
    file: UploadFile = File(...),
    description: str | None = Form(None),
    focus: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    data = await file.read()
    try:
        drive_file = await upload_drive_file(
            db=db, owner=user, data=data,
            filename=file.filename or "upload",
            mime_type=file.content_type or "application/octet-stream",
            description=description,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    focal_x, focal_y = _parse_focus(focus)
    if focal_x is not None and focal_y is not None:
        await update_drive_file_meta(db, drive_file, focal_x=focal_x, focal_y=focal_y)
    else:
        await auto_detect_focal_point(db, drive_file)

    return _to_media_attachment(drive_file)


@router.post("/api/v2/media", response_model=MediaAttachment)
async def upload_media_v2(
    file: UploadFile = File(...),
    description: str | None = Form(None),
    focus: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await upload_media_v1(
        file=file, description=description, focus=focus, user=user, db=db,
    )


@router.put("/api/v1/media/{file_id}", response_model=MediaAttachment)
async def update_media(
    file_id: uuid.UUID,
    description: str | None = Form(None),
    focus: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    drive_file = await get_drive_file(db, file_id)
    if not drive_file:
        raise HTTPException(status_code=404, detail="Media not found")
    if drive_file.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not allowed")

    focal_x, focal_y = _parse_focus(focus)
    await update_drive_file_meta(
        db, drive_file, description=description, focal_x=focal_x, focal_y=focal_y,
    )
    return _to_media_attachment(drive_file)


@router.get("/api/v1/media/{file_id}", response_model=MediaAttachment)
async def get_media(file_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    drive_file = await get_drive_file(db, file_id)
    if not drive_file:
        raise HTTPException(status_code=404, detail="Media not found")
    return _to_media_attachment(drive_file)


@router.delete("/api/v1/media/{file_id}")
async def delete_media(
    file_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    drive_file = await get_drive_file(db, file_id)
    if not drive_file:
        raise HTTPException(status_code=404, detail="Media not found")
    if drive_file.owner_id != user.id and not user.is_admin:
        raise HTTPException(status_code=403, detail="Not allowed")
    await delete_drive_file(db, drive_file)
    return {"ok": True}


@router.get("/api/v1/drive/files", response_model=list[DriveFileResponse])
async def list_drive_files(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    files = await list_user_files(db, user, limit=min(limit, 100), offset=offset)
    return [_to_drive_response(f) for f in files]
