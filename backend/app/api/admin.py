"""Admin-only API endpoints."""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.services.drive_service import file_to_url, upload_drive_file

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.post("/server-icon")
async def upload_server_icon(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")

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
