"""User data export: generate ZIP archive with AP data, CSVs, and media."""

import csv
import io
import json
import logging
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.activitypub.renderer import render_actor, render_create_activity
from app.config import settings
from app.models.bookmark import Bookmark
from app.models.data_export import DataExport
from app.models.drive_file import DriveFile
from app.models.follow import Follow
from app.models.note import Note
from app.models.user_block import UserBlock
from app.models.user_mute import UserMute
from app.storage import download_file, upload_file

logger = logging.getLogger(__name__)

EXPORT_EXPIRY = timedelta(days=7)
NOTE_BATCH_SIZE = 1000


def _actor_address(actor) -> str:
    """Return Mastodon-compatible account address (user@domain)."""
    if actor.domain:
        return f"{actor.username}@{actor.domain}"
    return f"{actor.username}@{settings.domain}"


async def generate_export(db: AsyncSession, export: DataExport) -> None:
    """Generate ZIP archive and upload to S3."""
    user = export.user
    actor = user.actor

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # 1. actor.json
        actor_data = render_actor(actor)
        zf.writestr("actor.json", json.dumps(actor_data, ensure_ascii=False, indent=2))

        # 2. outbox.json
        await _write_outbox(db, zf, actor)

        # 3. CSVs
        await _write_following_csv(db, zf, actor)
        await _write_followers_csv(db, zf, actor)
        await _write_bookmarks_csv(db, zf, actor)
        await _write_blocked_csv(db, zf, actor)
        await _write_muted_csv(db, zf, actor)

        # 4. media/
        await _write_media(db, zf, user)

    data = buf.getvalue()
    s3_key = f"exports/{user.id}/{export.id}.zip"
    await upload_file(s3_key, data, "application/zip")

    export.status = "completed"
    export.s3_key = s3_key
    export.size_bytes = len(data)
    export.expires_at = datetime.now(timezone.utc) + EXPORT_EXPIRY
    await db.flush()

    # Send completion email
    if settings.email_enabled and user.email:
        try:
            from app.services.email_queue import enqueue_email
            from app.services.email_service import _base_html

            download_url = (
                f"{settings.frontend_url}/settings/dataExport"
            )
            html_body = (
                f'<p>Your data export is ready.</p>'
                f'<p><a href="{download_url}" '
                f'style="background:#6364ff;color:white;padding:12px 30px;'
                f'border-radius:6px;text-decoration:none;font-weight:bold;">'
                f'Download</a></p>'
                f'<p style="font-size:13px;color:#666;">'
                f'This link expires in 7 days.</p>'
            )
            html = _base_html("Data Export Ready", html_body)
            text = (
                f"Your data export is ready.\n\n"
                f"Download it from: {download_url}\n\n"
                f"This link expires in 7 days.\n"
            )
            await enqueue_email(user.email, "Your data export is ready", html, text)
        except Exception:
            logger.exception("Failed to send export notification email")


async def _write_outbox(db: AsyncSession, zf: zipfile.ZipFile, actor) -> None:
    """Write all notes as AP OrderedCollection to outbox.json."""
    items = []
    offset = 0
    while True:
        result = await db.execute(
            select(Note)
            .where(Note.actor_id == actor.id, Note.deleted_at.is_(None))
            .options(
                selectinload(Note.attachments),
                selectinload(Note.actor),
                selectinload(Note.quoted_note).selectinload(Note.actor),
                selectinload(Note.in_reply_to).selectinload(Note.actor),
            )
            .order_by(Note.published.desc())
            .limit(NOTE_BATCH_SIZE)
            .offset(offset)
        )
        notes = list(result.scalars().all())
        if not notes:
            break
        for note in notes:
            try:
                items.append(render_create_activity(note))
            except Exception:
                logger.warning("Failed to render note %s", note.id)
        offset += NOTE_BATCH_SIZE

    outbox = {
        "@context": "https://www.w3.org/ns/activitystreams",
        "id": f"{settings.server_url}/users/{actor.username}/outbox",
        "type": "OrderedCollection",
        "totalItems": len(items),
        "orderedItems": items,
    }
    zf.writestr("outbox.json", json.dumps(outbox, ensure_ascii=False, indent=2))


async def _write_following_csv(
    db: AsyncSession, zf: zipfile.ZipFile, actor
) -> None:
    result = await db.execute(
        select(Follow)
        .where(Follow.follower_id == actor.id, Follow.accepted.is_(True))
        .options(selectinload(Follow.following))
    )
    follows = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Account address", "Show boosts", "Notify on new posts", "Languages"])
    for f in follows:
        writer.writerow([_actor_address(f.following), "true", "false", ""])
    zf.writestr("following_accounts.csv", buf.getvalue())


async def _write_followers_csv(
    db: AsyncSession, zf: zipfile.ZipFile, actor
) -> None:
    result = await db.execute(
        select(Follow)
        .where(Follow.following_id == actor.id, Follow.accepted.is_(True))
        .options(selectinload(Follow.follower))
    )
    follows = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Account address"])
    for f in follows:
        writer.writerow([_actor_address(f.follower)])
    zf.writestr("followers_accounts.csv", buf.getvalue())


async def _write_bookmarks_csv(
    db: AsyncSession, zf: zipfile.ZipFile, actor
) -> None:
    result = await db.execute(
        select(Note.ap_id)
        .join(Bookmark, Bookmark.note_id == Note.id)
        .where(Bookmark.actor_id == actor.id)
    )
    ap_ids = result.scalars().all()

    buf = io.StringIO()
    for ap_id in ap_ids:
        if ap_id:
            buf.write(ap_id + "\n")
    zf.writestr("bookmarks.csv", buf.getvalue())


async def _write_blocked_csv(
    db: AsyncSession, zf: zipfile.ZipFile, actor
) -> None:
    result = await db.execute(
        select(UserBlock)
        .where(UserBlock.actor_id == actor.id)
        .options(selectinload(UserBlock.target))
    )
    blocks = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Account address"])
    for b in blocks:
        writer.writerow([_actor_address(b.target)])
    zf.writestr("blocked_accounts.csv", buf.getvalue())


async def _write_muted_csv(
    db: AsyncSession, zf: zipfile.ZipFile, actor
) -> None:
    result = await db.execute(
        select(UserMute)
        .where(UserMute.actor_id == actor.id)
        .options(selectinload(UserMute.target))
    )
    mutes = result.scalars().all()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Account address", "Hide notifications", "Duration"])
    for m in mutes:
        writer.writerow([_actor_address(m.target), "true", ""])
    zf.writestr("muted_accounts.csv", buf.getvalue())


async def _write_media(
    db: AsyncSession, zf: zipfile.ZipFile, user
) -> None:
    """Download user's media files from S3 and add to ZIP."""
    result = await db.execute(
        select(DriveFile).where(
            DriveFile.owner_id == user.id, DriveFile.server_file.is_(False)
        )
    )
    files = result.scalars().all()

    for f in files:
        try:
            data = await download_file(f.s3_key)
            zf.writestr(f"media/{f.filename}", data)
        except Exception:
            logger.warning("Failed to download media %s (%s)", f.id, f.s3_key)
