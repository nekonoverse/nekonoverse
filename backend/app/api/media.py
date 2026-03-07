"""Media upload/download and drive API."""

import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.drive_file import DriveFile
from app.models.user import User
from app.schemas.media import DriveFileResponse, MediaAttachment
from app.services.drive_service import (
    delete_drive_file,
    file_to_url,
    get_drive_file,
    list_user_files,
    upload_drive_file,
)

router = APIRouter(tags=["media"])


def _to_media_attachment(f: DriveFile) -> MediaAttachment:
    url = file_to_url(f)
    meta = None
    if f.width and f.height:
        meta = {"original": {"width": f.width, "height": f.height}}
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
        server_file=f.server_file,
        created_at=f.created_at,
    )


@router.post("/api/v1/media", response_model=MediaAttachment)
async def upload_media_v1(
    file: UploadFile = File(...),
    description: str | None = Form(None),
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
    return _to_media_attachment(drive_file)


@router.post("/api/v2/media", response_model=MediaAttachment)
async def upload_media_v2(
    file: UploadFile = File(...),
    description: str | None = Form(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await upload_media_v1(file=file, description=description, user=user, db=db)


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
