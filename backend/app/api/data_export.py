"""User data export API endpoints."""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.data_export import DataExport
from app.models.user import User

router = APIRouter(prefix="/api/v1", tags=["export"])

EXPORT_COOLDOWN = timedelta(hours=24)


@router.post("/export")
async def start_export(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start a data export. Rate limited to once per 24 hours."""
    # Check cooldown
    result = await db.execute(
        select(DataExport)
        .where(
            DataExport.user_id == user.id,
            DataExport.created_at > datetime.now(timezone.utc) - EXPORT_COOLDOWN,
            DataExport.status.in_(["pending", "processing", "completed"]),
        )
        .order_by(DataExport.created_at.desc())
        .limit(1)
    )
    recent = result.scalar_one_or_none()
    if recent:
        raise HTTPException(
            status_code=429,
            detail="Export already requested. Please wait 24 hours.",
        )

    export = DataExport(user_id=user.id, status="pending")
    db.add(export)
    await db.commit()
    await db.refresh(export)

    from app.services.export_queue import enqueue_export

    await enqueue_export(str(export.id))

    return {"id": str(export.id), "status": export.status}


@router.get("/export")
async def get_export_status(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest export status."""
    result = await db.execute(
        select(DataExport)
        .where(DataExport.user_id == user.id)
        .order_by(DataExport.created_at.desc())
        .limit(1)
    )
    export = result.scalar_one_or_none()
    if not export:
        return None

    # Check expiry
    now = datetime.now(timezone.utc)
    if export.status == "completed" and export.expires_at and now > export.expires_at:
        return {
            "id": str(export.id),
            "status": "expired",
            "created_at": export.created_at.isoformat(),
        }

    return {
        "id": str(export.id),
        "status": export.status,
        "size_bytes": export.size_bytes,
        "error": export.error,
        "expires_at": export.expires_at.isoformat() if export.expires_at else None,
        "created_at": export.created_at.isoformat(),
    }


@router.get("/export/{export_id}/download")
async def download_export(
    export_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a completed export."""
    result = await db.execute(
        select(DataExport).where(
            DataExport.id == export_id, DataExport.user_id == user.id
        )
    )
    export = result.scalar_one_or_none()
    if not export:
        raise HTTPException(status_code=404, detail="Export not found")

    if export.status != "completed" or not export.s3_key:
        raise HTTPException(status_code=400, detail="Export not ready")

    now = datetime.now(timezone.utc)
    if export.expires_at and now > export.expires_at:
        raise HTTPException(status_code=410, detail="Export has expired")

    from app.storage import get_file_stream

    stream, content_type, size = await get_file_stream(export.s3_key)

    username = user.actor.username if user.actor else "user"
    filename = f"nekonoverse-export-{username}.zip"

    return StreamingResponse(
        stream,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(size) if size else "",
        },
    )
