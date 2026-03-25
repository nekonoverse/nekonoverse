"""Management CLI for nekonoverse.

Usage:
    python -m app.cli create-admin
    python -m app.cli reset-password
    python -m app.cli detect-focal-points
    python -m app.cli redetect-focal <note_id>
    python -m app.cli regenerate-icons [--from-default]
    python -m app.cli create-admin --username neko --email neko@example.com --password mypassword
"""

import argparse
import asyncio
import getpass
import re
import sys
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

# Import all models so SQLAlchemy relationships resolve correctly
import app.models.actor  # noqa: F401
import app.models.delivery  # noqa: F401
import app.models.drive_file  # noqa: F401
import app.models.follow  # noqa: F401
import app.models.note  # noqa: F401
import app.models.note_attachment  # noqa: F401
import app.models.oauth  # noqa: F401
import app.models.reaction  # noqa: F401
import app.models.user  # noqa: F401
from app.database import async_session, engine
from app.services.user_service import create_user, reset_password

_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]+$")


def _prompt(label: str, *, default: str | None = None, required: bool = True) -> str:
    suffix = f" [{default}]" if default else ""
    while True:
        value = input(f"{label}{suffix}: ").strip()
        if not value and default:
            return default
        if value:
            return value
        if not required:
            return ""
        print("  This field is required.")


def _prompt_password(label: str = "Password", *, confirm: bool = True, min_length: int = 8) -> str:
    while True:
        pw = getpass.getpass(f"{label}: ")
        if len(pw) < min_length:
            print(f"  Password must be at least {min_length} characters.")
            continue
        if confirm:
            pw2 = getpass.getpass(f"{label} (confirm): ")
            if pw != pw2:
                print("  Passwords do not match. Try again.")
                continue
        return pw


def _prompt_username() -> str:
    while True:
        username = _prompt("Username")
        if not _USERNAME_RE.match(username):
            print("  Username must be alphanumeric (a-z, 0-9, _).")
            continue
        if len(username) > 30:
            print("  Username must be 30 characters or less.")
            continue
        return username.lower()


def _interactive_create_admin() -> argparse.Namespace:
    print("\n  Create Admin User\n")
    args = argparse.Namespace()
    args.username = _prompt_username()
    args.email = _prompt("Email")
    args.password = _prompt_password()
    args.display_name = _prompt("Display name", default=args.username, required=False) or None
    print()
    return args


def _interactive_reset_password() -> argparse.Namespace:
    print("\n  Reset Password\n")
    args = argparse.Namespace()
    args.username = _prompt("Username")
    args.password = _prompt_password(label="New password")
    print()
    return args


async def _create_admin(args: argparse.Namespace) -> None:
    async with async_session() as db:
        db: AsyncSession
        try:
            user = await create_user(
                db=db,
                username=args.username,
                email=args.email,
                password=args.password,
                display_name=args.display_name,
                role="admin",
                skip_reserved_check=True,
            )
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Admin user created: {user.actor.username} ({user.email})")
        print(f"  role: {user.role}")
        print(f"  actor_id: {user.actor_id}")

    await engine.dispose()


async def _detect_focal_points(args: argparse.Namespace) -> None:
    from sqlalchemy import or_, select

    from app.config import settings
    from app.models.drive_file import DriveFile
    from app.models.note_attachment import NoteAttachment
    from app.services.drive_service import _read_file_data
    from app.services.face_detect_queue import _fetch_version
    from app.services.focal_point_service import _call_face_detect, _download_image

    if not settings.face_detect_enabled:
        print("Error: FACE_DETECT_URL or FACE_DETECT_UDS is not set.", file=sys.stderr)
        sys.exit(1)

    # Fetch current face-detect version for skip/record logic
    detect_version = await _fetch_version()
    if detect_version:
        print(f"Face-detect version: {detect_version}")
    else:
        print(
            "Warning: Could not fetch face-detect version,"
            " all undetected images will be processed."
        )

    concurrency = args.concurrency
    sem = asyncio.Semaphore(concurrency)

    # --- Local DriveFiles ---
    # Find images that need detection: version NULL (never checked) or outdated version
    # Skip: manual focal points, already checked with current version
    async with async_session() as db:
        conditions = [
            DriveFile.mime_type.startswith("image/"),
            DriveFile.focal_detect_version != "manual",
        ]
        if detect_version:
            conditions.append(
                or_(
                    DriveFile.focal_detect_version.is_(None),
                    DriveFile.focal_detect_version != detect_version,
                )
            )
        else:
            conditions.append(DriveFile.focal_detect_version.is_(None))

        rows = await db.execute(select(DriveFile).where(*conditions))
        local_files = list(rows.scalars().all())

    print(f"Local DriveFiles to process: {len(local_files)}")

    local_ok = 0
    local_noface = 0
    local_err = 0
    for i, df in enumerate(local_files, 1):
        async with sem:
            async with async_session() as db:
                merged = await db.merge(df)
                try:
                    image_data = await _read_file_data(merged)
                    if not image_data:
                        local_err += 1
                        continue
                    focal = await _call_face_detect(image_data, merged.width, merged.height)
                    if focal is None:
                        local_noface += 1
                    else:
                        merged.focal_x = focal[0]
                        merged.focal_y = focal[1]
                        local_ok += 1
                    # Record version so this file is skipped next time
                    if detect_version:
                        merged.focal_detect_version = detect_version
                    await db.commit()
                except Exception as e:
                    local_err += 1
                    print(f"\n  [error] {df.id}: {e}", file=sys.stderr)
        print(
            f"\r  [{i}/{len(local_files)}] ok={local_ok}"
            f" noface={local_noface} err={local_err}",
            end="", flush=True,
        )
    if local_files:
        print()

    # --- Remote NoteAttachments ---
    image_mimes = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/apng"}
    async with async_session() as db:
        conditions = [
            NoteAttachment.remote_url.isnot(None),
            NoteAttachment.remote_mime_type.in_(image_mimes),
            NoteAttachment.focal_detect_version != "manual",
        ]
        if detect_version:
            conditions.append(
                or_(
                    NoteAttachment.focal_detect_version.is_(None),
                    NoteAttachment.focal_detect_version != detect_version,
                )
            )
        else:
            conditions.append(NoteAttachment.focal_detect_version.is_(None))

        rows = await db.execute(select(NoteAttachment).where(*conditions))
        remote_atts = list(rows.scalars().all())

    print(f"Remote NoteAttachments to process: {len(remote_atts)}")

    remote_ok = 0
    remote_noface = 0
    remote_err = 0

    # "ok" / "noface" / "dl_err" / "detect_err"
    async def _process_remote(att: NoteAttachment) -> str:
        async with sem:
            image_data = await _download_image(att.remote_url)
            if not image_data:
                return "dl_err"
            focal = await _call_face_detect(image_data, att.remote_width, att.remote_height)
            if focal is None:
                # Record version so this attachment is skipped next time
                if detect_version:
                    att.focal_detect_version = detect_version
                return "noface"
            att.remote_focal_x = focal[0]
            att.remote_focal_y = focal[1]
            if detect_version:
                att.focal_detect_version = detect_version
            return "ok"

    # Process in batches to avoid holding too many sessions open
    batch_size = 50
    for batch_start in range(0, len(remote_atts), batch_size):
        batch = remote_atts[batch_start : batch_start + batch_size]
        async with async_session() as db:
            merged_batch = [await db.merge(att) for att in batch]
            results = await asyncio.gather(
                *(_process_remote(att) for att in merged_batch),
                return_exceptions=True,
            )
            for res in results:
                if res == "ok":
                    remote_ok += 1
                elif isinstance(res, Exception):
                    remote_err += 1
                    print(f"\n  [error] {res}", file=sys.stderr)
                elif res == "dl_err":
                    remote_err += 1
                else:
                    remote_noface += 1
            await db.commit()
        done = min(batch_start + batch_size, len(remote_atts))
        print(
            f"\r  [{done}/{len(remote_atts)}] ok={remote_ok}"
            f" noface={remote_noface} err={remote_err}",
            end="", flush=True,
        )
    if remote_atts:
        print()

    print(f"\nDone. Local: {local_ok} detected / {local_noface} noface / {local_err} errors. "
          f"Remote: {remote_ok} detected / {remote_noface} noface / {remote_err} errors.")

    await engine.dispose()


async def _redetect_focal(args: argparse.Namespace) -> None:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.config import settings
    from app.models.note import Note
    from app.models.note_attachment import NoteAttachment
    from app.services.drive_service import _read_file_data
    from app.services.face_detect_queue import _fetch_version
    from app.services.focal_point_service import (
        _call_face_detect,
        _download_image,
        _publish_update,
    )

    if not settings.face_detect_enabled:
        print("Error: FACE_DETECT_URL or FACE_DETECT_UDS is not set.", file=sys.stderr)
        sys.exit(1)

    detect_version = await _fetch_version()

    try:
        note_id = uuid.UUID(args.note_id)
    except ValueError:
        print(f"Error: Invalid UUID: {args.note_id}", file=sys.stderr)
        sys.exit(1)

    image_mimes = {"image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/apng"}

    async with async_session() as db:
        note = (
            await db.execute(
                select(Note)
                .options(selectinload(Note.attachments).selectinload(NoteAttachment.drive_file))
                .where(Note.id == note_id)
            )
        ).scalar_one_or_none()

        if not note:
            print(f"Error: Note {note_id} not found.", file=sys.stderr)
            sys.exit(1)

        attachments = [
            att for att in note.attachments
            if (att.drive_file and (att.drive_file.mime_type or "") in image_mimes)
            or ((att.remote_mime_type or "") in image_mimes and att.remote_url)
        ]

        if not attachments:
            print("No image attachments found for this note.")
            sys.exit(0)

        print(f"Note {note_id}: {len(attachments)} image attachment(s)\n")

        updated = False
        for i, att in enumerate(attachments, 1):
            if att.drive_file:
                # Local attachment
                df = att.drive_file
                print(f"  [{i}] Local: {df.s3_key} ({df.mime_type})")
                old = (df.focal_x, df.focal_y)
                try:
                    image_data = await _read_file_data(df)
                    if not image_data:
                        print("       -> ERROR: could not read file data")
                        continue
                    focal = await _call_face_detect(image_data, df.width, df.height)
                    if focal is None:
                        df.focal_x = None
                        df.focal_y = None
                        print(f"       -> no face detected (was {old})")
                    else:
                        df.focal_x = focal[0]
                        df.focal_y = focal[1]
                        print(f"       -> focal=({focal[0]:.4f}, {focal[1]:.4f}) (was {old})")
                    if detect_version:
                        df.focal_detect_version = detect_version
                    updated = True
                except Exception as e:
                    print(f"       -> ERROR: {e}")
            else:
                # Remote attachment
                print(f"  [{i}] Remote: {att.remote_url}")
                old = (att.remote_focal_x, att.remote_focal_y)
                try:
                    image_data = await _download_image(att.remote_url)
                    if not image_data:
                        print("       -> ERROR: could not download image")
                        continue
                    focal = await _call_face_detect(image_data, att.remote_width, att.remote_height)
                    if focal is None:
                        att.remote_focal_x = None
                        att.remote_focal_y = None
                        print(f"       -> no face detected (was {old})")
                    else:
                        att.remote_focal_x = focal[0]
                        att.remote_focal_y = focal[1]
                        print(f"       -> focal=({focal[0]:.4f}, {focal[1]:.4f}) (was {old})")
                    if detect_version:
                        att.focal_detect_version = detect_version
                    updated = True
                except Exception as e:
                    print(f"       -> ERROR: {e}")

        if updated:
            await db.commit()
            await _publish_update(note_id)
            print("\nDone. Changes committed and streaming update published.")
        else:
            print("\nNo changes made.")

    await engine.dispose()


async def _regenerate_icons(args: argparse.Namespace) -> None:
    from app.services.icon_service import _load_default_icon, generate_all_icons
    from app.services.server_settings_service import get_setting

    async with async_session() as db:
        if args.from_default:
            print("Using bundled default icon...")
            image_data = _load_default_icon()
        else:
            icon_url = await get_setting(db, "server_icon_url")
            if not icon_url:
                print("No server_icon_url configured. Use --from-default to use bundled icon.")
                sys.exit(1)

            # Download current server icon from S3
            print(f"Downloading current server icon: {icon_url}")
            import httpx

            from app.utils.http_client import USER_AGENT
            async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}) as client:
                resp = await client.get(icon_url)
                if resp.status_code != 200:
                    print(f"Error: Failed to download icon (HTTP {resp.status_code})")
                    sys.exit(1)
                image_data = resp.content

        print("Generating icons...")
        urls = await generate_all_icons(db, image_data, set_server_icon=args.from_default)
        for key, url in urls.items():
            print(f"  {key}: {url}")

    await engine.dispose()
    print("Done.")


async def _reset_password(args: argparse.Namespace) -> None:
    async with async_session() as db:
        try:
            user = await reset_password(db, args.username, args.password)
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        print(f"Password reset for: {user.actor.username} ({user.email})")

    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(prog="nekonoverse", description="nekonoverse management CLI")
    sub = parser.add_subparsers(dest="command")

    create_admin = sub.add_parser("create-admin", help="Create an admin user")
    create_admin.add_argument("--username", default=None)
    create_admin.add_argument("--email", default=None)
    create_admin.add_argument("--password", default=None)
    create_admin.add_argument("--display-name", dest="display_name", default=None)

    reset_pw = sub.add_parser("reset-password", help="Reset a user's password")
    reset_pw.add_argument("--username", default=None)
    reset_pw.add_argument("--password", default=None)

    detect_fp = sub.add_parser(
        "detect-focal-points",
        help="Run face detection on images needing detection",
    )
    detect_fp.add_argument(
        "--concurrency", type=int, default=4,
        help="Max concurrent requests (default: 4)",
    )

    redetect = sub.add_parser(
        "redetect-focal",
        help="Force re-detect focal point for a specific note",
    )
    redetect.add_argument("note_id", type=str, help="Note ID (UUID)")

    regen_icons = sub.add_parser("regenerate-icons", help="Regenerate favicon and PWA icons")
    regen_icons.add_argument(
        "--from-default", action="store_true",
        help="Use bundled default icon instead of current server icon",
    )

    args = parser.parse_args()

    if args.command == "create-admin":
        if not (args.username and args.email and args.password):
            args = _interactive_create_admin()
        asyncio.run(_create_admin(args))
    elif args.command == "reset-password":
        if not (args.username and args.password):
            args = _interactive_reset_password()
        asyncio.run(_reset_password(args))
    elif args.command == "detect-focal-points":
        asyncio.run(_detect_focal_points(args))
    elif args.command == "redetect-focal":
        asyncio.run(_redetect_focal(args))
    elif args.command == "regenerate-icons":
        asyncio.run(_regenerate_icons(args))
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
