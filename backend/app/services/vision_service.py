"""画像自動タグ付け/キャプション生成サービス。

neko-vision マイクロサービスを呼び出してタグとキャプションを生成し、
DriveFile / NoteAttachment に保存する。
"""

import asyncio
import base64
import logging
import re
import uuid
from datetime import datetime, timezone
from html import unescape

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings

logger = logging.getLogger(__name__)

_IMAGE_MIMES = frozenset({
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/avif", "image/apng",
})
_MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


def _strip_html(html: str) -> str:
    """HTMLタグを除去してプレーンテキストにする。"""
    text = re.sub(r"<br\s*/?>", "\n", html)
    text = re.sub(r"<[^>]+>", "", text)
    return unescape(text).strip()


async def collect_reply_context(
    db: AsyncSession,
    note,
    max_depth: int = 5,
) -> list[str]:
    """リプライツリーの親ノート本文を収集する（古い順）。

    in_reply_to_id を辿って最大 max_depth 件の親ノート本文を取得する。
    """
    from sqlalchemy import select

    from app.models.note import Note

    context: list[str] = []
    current_id = note.in_reply_to_id

    for _ in range(max_depth):
        if not current_id:
            break
        result = await db.execute(
            select(Note.content, Note.in_reply_to_id).where(Note.id == current_id)
        )
        row = result.one_or_none()
        if not row:
            break
        content, next_id = row
        text = _strip_html(content) if content else ""
        if text:
            context.append(text[:300])
        current_id = next_id

    context.reverse()  # 古い順に並べる
    return context


async def auto_tag_image(
    db: AsyncSession,
    drive_file,
    *,
    image_data: bytes | None = None,
    note_text: str | None = None,
    context: list[str] | None = None,
) -> None:
    """ローカルDriveFileのタグ付けを実行する。失敗時は無視する。"""
    if not settings.neko_vision_enabled:
        return
    if not drive_file.mime_type.startswith("image/"):
        return

    try:
        if not image_data:
            image_data = await _read_file_data(drive_file)
            if not image_data:
                logger.warning("Could not read file %s from S3", drive_file.s3_key)
                return

        logger.info("Running vision tagging for %s", drive_file.id)
        result = await _call_vision(image_data, note_text=note_text, context=context)
        if not result:
            return

        drive_file.vision_tags = result["tags"]
        drive_file.vision_caption = result["caption"]
        drive_file.vision_at = datetime.now(timezone.utc)
        await db.commit()
        logger.info(
            "Vision tags set for %s: %d tags, caption=%d chars",
            drive_file.id,
            len(result["tags"]),
            len(result["caption"]),
        )
    except Exception:
        logger.warning("Vision tagging failed for %s", drive_file.id, exc_info=True)


async def tag_remote_attachments(
    note_id: uuid.UUID,
    attachment_ids: list[uuid.UUID],
    *,
    note_text: str | None = None,
    context: list[str] | None = None,
) -> None:
    """リモート添付ファイルのバッチタグ付け。

    各リモート画像をダウンロードし、neko-vision を呼び出し、DBを更新する。
    """
    if not settings.neko_vision_enabled:
        return

    from app.database import async_session

    try:
        async with async_session() as db:
            from sqlalchemy import select

            from app.models.note_attachment import NoteAttachment

            rows = await db.execute(
                select(NoteAttachment).where(NoteAttachment.id.in_(attachment_ids))
            )
            attachments = list(rows.scalars().all())

            results = await asyncio.gather(
                *(
                    _tag_single_remote(att, note_text=note_text, context=context)
                    for att in attachments
                ),
                return_exceptions=True,
            )

            changed = False
            for att, res in zip(attachments, results):
                if isinstance(res, Exception):
                    logger.warning("Vision tagging failed for %s: %s", att.id, res)
                elif res is True:
                    changed = True

            if changed or any(not isinstance(r, Exception) for r in results):
                await db.commit()
                if changed:
                    logger.info("Vision tags updated for note %s", note_id)
    except Exception:
        logger.warning(
            "Background vision tagging failed for note %s", note_id, exc_info=True
        )


async def _tag_single_remote(
    att,
    *,
    note_text: str | None = None,
    context: list[str] | None = None,
) -> bool:
    """1つのリモート添付ファイルをタグ付けする。更新された場合はTrueを返す。"""
    if not att.remote_url:
        return False
    if (att.remote_mime_type or "") not in _IMAGE_MIMES:
        return False

    image_data = await _download_image(att.remote_url)
    if not image_data:
        return False

    result = await _call_vision(image_data, note_text=note_text, context=context)
    if not result:
        return False

    att.remote_vision_tags = result["tags"]
    att.remote_vision_caption = result["caption"]
    att.vision_at = datetime.now(timezone.utc)
    return True


async def _call_vision(
    image_data: bytes,
    *,
    note_text: str | None = None,
    context: list[str] | None = None,
) -> dict | None:
    """neko-vision API を呼び出す。{"tags": [...], "caption": "..."} を返す。"""
    from app.utils.http_client import make_neko_vision_client

    b64 = base64.b64encode(image_data).decode("ascii")
    payload: dict = {"image": b64}
    if note_text:
        payload["text"] = _strip_html(note_text)[:500]
    if context:
        payload["context"] = context

    base = settings.neko_vision_base_url.rstrip("/")
    # URL が /tag で終わっていなければ追加
    url = base if base.endswith("/tag") else f"{base}/tag"

    async with make_neko_vision_client() as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    tags = data.get("tags", [])
    caption = data.get("caption", "")

    if not tags and not caption:
        return None

    return {"tags": tags, "caption": caption}


async def _read_file_data(drive_file) -> bytes | None:
    """S3からファイルデータを読み込む。"""
    try:
        from app.services.drive_service import _get_s3_client

        async with _get_s3_client() as s3:
            resp = await s3.get_object(Bucket=settings.s3_bucket, Key=drive_file.s3_key)
            return await resp["Body"].read()
    except Exception:
        logger.warning("Failed to read %s from S3", drive_file.s3_key, exc_info=True)
        return None


async def _download_image(url: str) -> bytes | None:
    """SSRF保護付きでリモート画像をダウンロードする。focal_point_serviceと同じロジック。"""
    from urllib.parse import urljoin, urlparse

    from app.utils.network import is_private_host

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None
    if is_private_host(parsed.hostname):
        return None

    import httpx

    from app.utils.http_client import make_async_client

    async with make_async_client(
        timeout=httpx.Timeout(15.0, connect=5.0),
        follow_redirects=False,
        verify=not settings.skip_ssl_verify,
    ) as client:
        current_url = url
        for _ in range(3):
            resp = await client.get(current_url)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return None
                resolved = urljoin(current_url, location)
                rp = urlparse(resolved)
                if rp.scheme not in ("http", "https") or not rp.hostname:
                    return None
                if is_private_host(rp.hostname):
                    return None
                current_url = resolved
            else:
                break
        else:
            return None

        if resp.status_code != 200:
            return None
        if len(resp.content) > _MAX_DOWNLOAD_BYTES:
            return None
        return resp.content


