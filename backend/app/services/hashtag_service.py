import re
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hashtag import Hashtag, NoteHashtag

# ハッシュタグにマッチ: ASCII英数字/アンダースコアおよび日本語文字
_HASHTAG_RE = re.compile(r"#([a-zA-Z0-9_\u3041-\u9fff\u30a0-\u30ff\uff66-\uff9f]+)")


def extract_hashtags(text: str) -> list[str]:
    """テキストからハッシュタグ名を抽出し、小文字化して重複排除する。"""
    seen: set[str] = set()
    result: list[str] = []
    for match in _HASHTAG_RE.finditer(text):
        tag = match.group(1).lower()
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result


def extract_hashtags_from_ap_tags(tags: list[dict]) -> list[str]:
    """ActivityPub の tag 配列からハッシュタグ名を抽出する。"""
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        if tag.get("type") != "Hashtag":
            continue
        name = tag.get("name", "")
        # AP のハッシュタグは通常 # プレフィックス付き
        name = name.lstrip("#").lower()
        if name and name not in seen:
            seen.add(name)
            result.append(name)
    return result


async def upsert_hashtags(
    db: AsyncSession,
    note_id: uuid.UUID,
    hashtag_names: list[str],
) -> None:
    """ハッシュタグを作成または更新し、ノートに紐付ける。"""
    if not hashtag_names:
        return

    now = datetime.now(timezone.utc)

    # 既存ハッシュタグを一括取得
    result = await db.execute(select(Hashtag).where(Hashtag.name.in_(hashtag_names)))
    existing_tags = {h.name: h for h in result.scalars().all()}

    # 既存の関連を一括チェック
    tag_ids = [h.id for h in existing_tags.values()]
    existing_links: set[uuid.UUID] = set()
    if tag_ids:
        link_result = await db.execute(
            select(NoteHashtag.hashtag_id).where(
                NoteHashtag.note_id == note_id,
                NoteHashtag.hashtag_id.in_(tag_ids),
            )
        )
        existing_links = set(link_result.scalars().all())

    for name in hashtag_names:
        hashtag = existing_tags.get(name)
        if hashtag:
            hashtag.usage_count = hashtag.usage_count + 1
            hashtag.last_used_at = now
        else:
            hashtag = Hashtag(
                name=name,
                usage_count=1,
                last_used_at=now,
            )
            db.add(hashtag)
            await db.flush()

        if hashtag.id not in existing_links:
            db.add(NoteHashtag(note_id=note_id, hashtag_id=hashtag.id))

    await db.flush()


async def get_trending_tags(
    db: AsyncSession,
    limit: int = 10,
) -> list[Hashtag]:
    """使用回数が最も多いハッシュタグを usage_count 降順で返す。"""
    result = await db.execute(select(Hashtag).order_by(Hashtag.usage_count.desc()).limit(limit))
    return list(result.scalars().all())


async def get_notes_by_hashtag(
    db: AsyncSession,
    tag_name: str,
    limit: int = 20,
    max_id: uuid.UUID | None = None,
    current_actor_id: uuid.UUID | None = None,
) -> list:
    """特定のハッシュタグを持つノートを published 降順で返す。"""
    from app.models.actor import Actor
    from app.models.note import Note
    from app.services.note_service import _get_excluded_ids, _note_load_options

    tag_name_lower = tag_name.lower()

    query = (
        select(Note)
        .join(NoteHashtag, NoteHashtag.note_id == Note.id)
        .join(Hashtag, Hashtag.id == NoteHashtag.hashtag_id)
        .join(Actor, Note.actor_id == Actor.id)
        .options(*_note_load_options())
        .where(
            Hashtag.name == tag_name_lower,
            Note.visibility == "public",
            Note.deleted_at.is_(None),
            Actor.silenced_at.is_(None),
        )
    )

    if current_actor_id:
        excluded = await _get_excluded_ids(db, current_actor_id)
        if excluded:
            query = query.where(Note.actor_id.not_in(excluded))
    else:
        query = query.where(Actor.require_signin_to_view.is_(False))

    if max_id:
        sub = select(Note.published).where(Note.id == max_id).scalar_subquery()
        query = query.where(Note.published < sub)

    query = query.order_by(Note.published.desc()).limit(limit)
    result = await db.execute(query)
    return list(result.scalars().all())


async def get_hashtags_for_note(
    db: AsyncSession,
    note_id: uuid.UUID,
) -> list[str]:
    """指定されたノートのハッシュタグ名一覧を返す。"""
    result = await db.execute(
        select(Hashtag.name)
        .join(NoteHashtag, NoteHashtag.hashtag_id == Hashtag.id)
        .where(NoteHashtag.note_id == note_id)
    )
    return [row[0] for row in result.all()]


async def get_hashtags_for_notes(
    db: AsyncSession,
    note_ids: list[uuid.UUID],
) -> dict[uuid.UUID, list[str]]:
    """複数ノートのハッシュタグ名を単一クエリで返す。

    note_id -> ハッシュタグ名リストの辞書を返す。
    """
    if not note_ids:
        return {}

    result = await db.execute(
        select(NoteHashtag.note_id, Hashtag.name)
        .join(Hashtag, Hashtag.id == NoteHashtag.hashtag_id)
        .where(NoteHashtag.note_id.in_(note_ids))
    )

    tags_map: dict[uuid.UUID, list[str]] = {nid: [] for nid in note_ids}
    for note_id_val, tag_name in result.all():
        tags_map[note_id_val].append(tag_name)
    return tags_map
