"""neko-vision 再判定CLI。

指定日以前にタグ付けされた画像を neko_vision:queue に再エンキューする。

Usage:
    python -m scripts.vision_retag --before 2026-03-01
    python -m scripts.vision_retag --before 2026-03-01 --dry-run
    python -m scripts.vision_retag --before 2026-03-01 --limit 100
    python -m scripts.vision_retag --all  # 全画像を再判定
"""

import argparse
import asyncio
import json
import logging
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vision_retag")


async def main():
    parser = argparse.ArgumentParser(description="neko-vision 再判定CLI")
    parser.add_argument(
        "--before",
        type=str,
        help="この日付(YYYY-MM-DD)以前にタグ付けされた画像を再判定",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="タグ付け済みの全画像を再判定",
    )
    parser.add_argument(
        "--untagged",
        action="store_true",
        help="未タグ付けの画像のみエンキュー",
    )
    parser.add_argument("--dry-run", action="store_true", help="件数確認のみ")
    parser.add_argument("--limit", type=int, default=0, help="処理件数制限 (0=無制限)")
    args = parser.parse_args()

    if not args.before and not args.all and not args.untagged:
        parser.error("--before, --all, --untagged のいずれかを指定してください")

    from app.config import settings

    if not settings.neko_vision_enabled:
        logger.error("NEKO_VISION_URL/UDS が設定されていません")
        return

    cutoff = None
    if args.before:
        cutoff = datetime.strptime(args.before, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    from sqlalchemy import select

    from app.database import async_session
    from app.models.drive_file import DriveFile
    from app.models.note_attachment import NoteAttachment
    from app.valkey_client import valkey as valkey_client

    queue_key = "neko_vision:queue"
    local_count = 0
    remote_count = 0

    async with async_session() as db:
        # ローカルDriveFile
        q = select(DriveFile.id).where(DriveFile.mime_type.like("image/%"))
        if args.untagged:
            q = q.where(DriveFile.vision_at.is_(None))
        elif args.all:
            pass  # 全件
        elif cutoff:
            from sqlalchemy import or_

            q = q.where(
                or_(
                    DriveFile.vision_at.is_(None),
                    DriveFile.vision_at < cutoff,
                )
            )
        if args.limit:
            q = q.limit(args.limit)

        rows = await db.execute(q)
        local_ids = [row[0] for row in rows.all()]
        local_count = len(local_ids)

        # リモートNoteAttachment
        q2 = select(NoteAttachment.id, NoteAttachment.note_id).where(
            NoteAttachment.remote_url.isnot(None),
            NoteAttachment.remote_mime_type.in_(
                ["image/jpeg", "image/png", "image/webp", "image/gif",
                 "image/avif", "image/apng"]
            ),
        )
        if args.untagged:
            q2 = q2.where(NoteAttachment.vision_at.is_(None))
        elif args.all:
            pass
        elif cutoff:
            from sqlalchemy import or_

            q2 = q2.where(
                or_(
                    NoteAttachment.vision_at.is_(None),
                    NoteAttachment.vision_at < cutoff,
                )
            )
        if args.limit:
            remaining = max(0, args.limit - local_count)
            q2 = q2.limit(remaining)

        rows2 = await db.execute(q2)
        by_note: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
        for att_id, note_id in rows2.all():
            by_note[note_id].append(att_id)
            remote_count += 1

    logger.info(
        "対象: ローカル %d件, リモート %d件 (%dノート)",
        local_count, remote_count, len(by_note),
    )

    if args.dry_run:
        logger.info("dry-run モード: エンキューしません")
        return

    # エンキュー
    for fid in local_ids:
        # ローカルファイルはノート本文なしでエンキュー（再判定のため）
        job = {
            "type": "local",
            "drive_file_id": str(fid),
            "attempts": 0,
            "created_at": time.time(),
        }
        await valkey_client.lpush(queue_key, json.dumps(job))

    for note_id, att_ids in by_note.items():
        job = {
            "type": "remote",
            "note_id": str(note_id),
            "attachment_ids": [str(a) for a in att_ids],
            "attempts": 0,
            "created_at": time.time(),
        }
        await valkey_client.lpush(queue_key, json.dumps(job))

    logger.info("エンキュー完了: ローカル %d件, リモート %d件", local_count, remote_count)


if __name__ == "__main__":
    asyncio.run(main())
