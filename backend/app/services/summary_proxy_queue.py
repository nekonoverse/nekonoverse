"""URL要約/OGP抽出用のValkeyベースジョブキュー。

ジョブはJSON形式でValkeyリストに保存される。ワーカーがジョブをポップし、
summary-proxy外部サービスを呼び出して、PreviewCardレコードを保存する。

ジョブ形式: {"note_id": "<uuid>", "url": "<url>", "attempts": 0, "created_at": <ts>}
"""

import asyncio
import json
import logging
import time
import uuid

from app.config import settings
from app.valkey_client import valkey as valkey_client

logger = logging.getLogger(__name__)

QUEUE_KEY = "summary_proxy:queue"
DELAYED_KEY = "summary_proxy:delayed"
DEAD_KEY = "summary_proxy:dead"
HEARTBEAT_KEY = "worker:summary_proxy:heartbeat"

MAX_ATTEMPTS = 3
MAX_CONCURRENT = 4


async def enqueue(note_id: uuid.UUID, url: str) -> None:
    """ノートのURL要約抽出をキューに追加する。"""
    if not settings.summary_proxy_url:
        return
    job = {
        "note_id": str(note_id),
        "url": url,
        "attempts": 0,
        "created_at": time.time(),
    }
    await valkey_client.lpush(QUEUE_KEY, json.dumps(job))
    logger.debug("Enqueued summary-proxy job for note %s url %s", note_id, url)


async def _process_job(job: dict) -> None:
    """外部サービスから要約を取得し、PreviewCardとして保存する。"""
    from sqlalchemy import select

    from app.database import async_session
    from app.models.preview_card import PreviewCard
    from app.utils.http_client import make_summary_proxy_client

    note_id = uuid.UUID(job["note_id"])
    url = job["url"]

    # カードが既に存在するか確認 (冪等性)
    async with async_session() as db:
        existing = await db.execute(
            select(PreviewCard).where(PreviewCard.note_id == note_id)
        )
        if existing.scalar_one_or_none():
            return

    # summary-proxy サービスを呼び出す
    base_url = settings.summary_proxy_url
    async with make_summary_proxy_client() as client:
        resp = await client.get(
            f"{base_url}/summary",
            params={"url": url},
        )
        resp.raise_for_status()
        data = resp.json()

    title = data.get("title")
    description = data.get("description")
    thumbnail = data.get("thumbnail")
    site_name = data.get("siteName")

    # 有用なメタデータが抽出できなかった場合はスキップ
    if not title and not description:
        logger.debug("No useful metadata for %s, skipping card creation", url)
        return

    # サムネイルURLをメディアプロキシURLに変換
    image_url = None
    if thumbnail:
        from app.utils.media_proxy import media_proxy_url

        image_url = media_proxy_url(thumbnail, variant="preview")

    async with async_session() as db:
        # 冪等性のため再チェック
        existing = await db.execute(
            select(PreviewCard).where(PreviewCard.note_id == note_id)
        )
        if existing.scalar_one_or_none():
            return

        card = PreviewCard(
            note_id=note_id,
            url=url,
            title=(title or "")[:500] if title else None,
            description=description,
            image=image_url,
            site_name=(site_name or "")[:200] if site_name else None,
        )
        db.add(card)
        await db.commit()
        logger.info("Created preview card for note %s: %s", note_id, title)


async def _retry_or_dead(job: dict, error: str) -> None:
    """バックオフ付きで再キューするか、デッドレターに移動する。"""
    job["attempts"] = job.get("attempts", 0) + 1
    job["last_error"] = error

    if job["attempts"] >= MAX_ATTEMPTS:
        await valkey_client.lpush(DEAD_KEY, json.dumps(job))
        logger.warning(
            "Summary-proxy job dead-lettered after %d attempts: %s",
            job["attempts"], error,
        )
    else:
        delay = min(30 * (2 ** job["attempts"]), 3600)
        run_at = time.time() + delay
        await valkey_client.zadd(DELAYED_KEY, {json.dumps(job): run_at})
        logger.info(
            "Summary-proxy job retry #%d in %ds: %s",
            job["attempts"], delay, error,
        )


async def _promote_delayed() -> int:
    """run_at が経過した遅延ジョブをメインキューに戻す。"""
    now = time.time()
    ready = await valkey_client.zrangebyscore(DELAYED_KEY, "-inf", str(now), start=0, num=50)
    if not ready:
        return 0
    for raw in ready:
        await valkey_client.lpush(QUEUE_KEY, raw)
    await valkey_client.zremrangebyscore(DELAYED_KEY, "-inf", str(now))
    return len(ready)


async def _update_heartbeat() -> None:
    """summary-proxy ワーカーのハートビートを更新する。"""
    try:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc).isoformat()
        await valkey_client.set(HEARTBEAT_KEY, now, ex=30)
    except Exception:
        pass


async def run_summary_proxy_loop() -> None:
    """summary-proxy ワーカーのメインループ。"""
    if not settings.summary_proxy_url:
        logger.info("SUMMARY_PROXY_URL not set, summary-proxy worker idle")
        while True:
            await asyncio.sleep(30)

    logger.info("Summary-proxy worker started (max_concurrent=%d)", MAX_CONCURRENT)
    sem = asyncio.Semaphore(MAX_CONCURRENT)

    async def _run_one(raw: str) -> None:
        async with sem:
            try:
                job = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("Invalid summary-proxy job JSON: %s", raw[:200])
                return
            try:
                await _process_job(job)
            except Exception as e:
                await _retry_or_dead(job, str(e))

    tasks: set[asyncio.Task] = set()

    while True:
        try:
            await _update_heartbeat()
            await _promote_delayed()

            result = await valkey_client.brpop(QUEUE_KEY, timeout=3)
            if result:
                _, raw = result
                task = asyncio.create_task(_run_one(raw))
                tasks.add(task)
                task.add_done_callback(tasks.discard)
        except Exception:
            logger.exception("Error in summary-proxy worker loop")
            await asyncio.sleep(5)
