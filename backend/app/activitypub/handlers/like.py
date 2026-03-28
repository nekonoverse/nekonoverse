"""Like および EmojiReact activity を処理する (Misskey/Pleroma 互換)。"""

import logging
import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reaction import Reaction
from app.services.actor_service import fetch_remote_actor, get_actor_by_ap_id
from app.services.note_service import get_note_by_ap_id
from app.utils.emoji import is_custom_emoji_shortcode, is_single_emoji

_CUSTOM_EMOJI_RE = re.compile(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:$")

logger = logging.getLogger(__name__)


async def handle_like(db: AsyncSession, activity: dict):
    """Like activity を処理する -- Misskey 形式の _misskey_reaction を含む場合がある。"""
    actor_ap_id = activity.get("actor")
    note_ap_id = activity.get("object")

    if not actor_ap_id or not note_ap_id:
        return

    # 絵文字を特定
    misskey_reaction = activity.get("_misskey_reaction")
    content = activity.get("content")

    if misskey_reaction:
        emoji = misskey_reaction
    elif content and is_single_emoji(content):
        emoji = content
    else:
        emoji = "\u2b50"  # ⭐ — 素の Like (例: Mastodon から) = お気に入り

    # tag 配列からカスタム絵文字をキャッシュ
    if is_custom_emoji_shortcode(emoji):
        await _cache_custom_emoji(db, activity, emoji)

    await _save_reaction(db, activity, actor_ap_id, note_ap_id, emoji)


async def handle_emoji_react(db: AsyncSession, activity: dict):
    """EmojiReact activity を処理する (Pleroma/Akkoma 形式)。"""
    actor_ap_id = activity.get("actor")
    note_ap_id = activity.get("object")
    content = activity.get("content")

    if not actor_ap_id or not note_ap_id:
        return

    emoji = (
        content
        if content and (is_single_emoji(content) or is_custom_emoji_shortcode(content))
        else "\u2764"
    )
    if is_custom_emoji_shortcode(emoji):
        await _cache_custom_emoji(db, activity, emoji)
    await _save_reaction(db, activity, actor_ap_id, note_ap_id, emoji)


async def _normalize_emoji_to_local(db: AsyncSession, emoji: str) -> str:
    """リモートカスタム絵文字にローカル版がある場合、ローカル版を使用する。"""
    m = _CUSTOM_EMOJI_RE.match(emoji)
    if not m or not m.group(2):
        return emoji
    from app.services.emoji_service import get_custom_emoji

    local = await get_custom_emoji(db, m.group(1), None)
    return f":{m.group(1)}:" if local else emoji


async def _save_reaction(
    db: AsyncSession,
    activity: dict,
    actor_ap_id: str,
    note_ap_id: str,
    emoji: str,
):
    # 利用可能であればリモート絵文字をローカル版に正規化
    emoji = await _normalize_emoji_to_local(db, emoji)

    # アクターを解決
    actor = await get_actor_by_ap_id(db, actor_ap_id)
    if not actor:
        actor = await fetch_remote_actor(db, actor_ap_id)
    if not actor:
        logger.warning("Could not resolve actor %s for reaction", actor_ap_id)
        return

    # ノートを解決
    note = await get_note_by_ap_id(db, note_ap_id)
    if not note:
        logger.info("Note not found for reaction: %s", note_ap_id)
        return

    # 重複をチェック
    existing = await db.execute(
        select(Reaction).where(
            Reaction.actor_id == actor.id,
            Reaction.note_id == note.id,
            Reaction.emoji == emoji,
        )
    )
    if existing.scalar_one_or_none():
        return

    reaction = Reaction(
        ap_id=activity.get("id"),
        actor_id=actor.id,
        note_id=note.id,
        emoji=emoji,
    )
    db.add(reaction)

    # リアクション数を更新
    note.reactions_count = note.reactions_count + 1
    await db.flush()

    # ローカルのノート作成者に通知
    notif = None
    if note.actor and note.actor.is_local:
        from app.services.notification_service import create_notification

        notif = await create_notification(
            db,
            "reaction",
            note.actor_id,
            actor.id,
            note.id,
            reaction_emoji=emoji,
        )

    await db.commit()

    if notif:
        from app.services.notification_service import publish_notification

        await publish_notification(notif)

    from app.services.reaction_service import _publish_reaction_event

    await _publish_reaction_event(db, note)

    logger.info("Saved reaction %s from %s on %s", emoji, actor_ap_id, note_ap_id)


async def _cache_custom_emoji(db: AsyncSession, activity: dict, emoji_str: str):
    """activity の tag 配列からカスタム絵文字をキャッシュする。"""
    match = _CUSTOM_EMOJI_RE.match(emoji_str)
    if not match:
        return

    shortcode = match.group(1)
    domain = match.group(2)

    # ドメインを早期に特定 (タグベースとフォールバックの両方のキャッシュに必要)
    if not domain:
        actor_ap_id = activity.get("actor", "")
        from urllib.parse import urlparse

        domain = urlparse(actor_ap_id).hostname

    tags = activity.get("tag", [])
    if isinstance(tags, dict):
        tags = [tags]
    found_tag = False
    for tag in tags:
        if (
            isinstance(tag, dict)
            and tag.get("type") == "Emoji"
            and tag.get("name", "").strip(":") == shortcode
        ):
            icon = tag.get("icon", {})
            url = icon.get("url") if isinstance(icon, dict) else None
            if url and domain:
                from app.services.emoji_service import upsert_remote_emoji

                # 拡張フィールドを抽出 (Misskey + CherryPick)
                static_url = icon.get("staticUrl") if isinstance(icon, dict) else None
                _ml = tag.get("_misskey_license")
                license_text = tag.get("license") or (
                    _ml.get("freeText") if isinstance(_ml, dict) else None
                )
                await upsert_remote_emoji(
                    db,
                    shortcode,
                    domain,
                    url,
                    static_url=static_url,
                    aliases=tag.get("keywords"),
                    license=license_text,
                    is_sensitive=bool(tag.get("isSensitive", False)),
                    author=tag.get("author") or tag.get("creator"),
                    description=tag.get("description"),
                    copy_permission=tag.get("copyPermission"),
                    usage_info=tag.get("usageInfo"),
                    is_based_on=tag.get("isBasedOn"),
                    category=tag.get("category"),
                )
                found_tag = True
            break

    # フォールバック: タグが見つからなかった場合はリモートインスタンスの API からフェッチ
    if not found_tag and domain:
        from app.services.emoji_service import fetch_and_cache_remote_emoji

        await fetch_and_cache_remote_emoji(db, shortcode, domain)
