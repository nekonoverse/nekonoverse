import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.note import Note
from app.models.reaction import Reaction
from app.models.user import User
from app.services.actor_service import actor_uri
from app.utils.emoji import is_custom_emoji_shortcode, is_single_emoji


async def _publish_reaction_event(db: AsyncSession, note: Note) -> None:
    """Valkey pub/sub経由でリアルタイムリアクションイベントをパブリッシュする。"""
    try:
        import json

        from app.services.follow_service import get_follower_ids
        from app.valkey_client import valkey as valkey_client

        event = json.dumps(
            {
                "event": "status.reaction",
                "payload": {"id": str(note.id)},
            }
        )

        if note.visibility == "public":
            await valkey_client.publish("timeline:public", event)

        await valkey_client.publish(f"timeline:home:{note.actor_id}", event)

        follower_ids = await get_follower_ids(db, note.actor_id)
        for fid in follower_ids:
            await valkey_client.publish(f"timeline:home:{fid}", event)
    except Exception:
        pass


async def add_reaction(db: AsyncSession, user: User, note: Note, emoji: str) -> Reaction:
    """ノートにリアクションを追加する。"""
    if not is_single_emoji(emoji) and not is_custom_emoji_shortcode(emoji):
        raise ValueError("Invalid emoji")

    actor = user.actor

    # 重複チェック
    existing = await db.execute(
        select(Reaction).where(
            Reaction.actor_id == actor.id,
            Reaction.note_id == note.id,
            Reaction.emoji == emoji,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Already reacted with this emoji")

    reaction_id = uuid.uuid4()
    ap_id = f"{settings.server_url}/activities/{reaction_id}"

    reaction = Reaction(
        id=reaction_id,
        ap_id=ap_id,
        actor_id=actor.id,
        note_id=note.id,
        emoji=emoji,
    )
    db.add(reaction)
    note.reactions_count += 1
    # L-11: 競合状態対策 -- DB一意制約違反時は既存リアクションとして扱う
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise ValueError("Already reacted with this emoji")

    await _publish_reaction_event(db, note)

    # 連合用のアクティビティを構築
    from app.activitypub.renderer import (
        render_emoji_react_activity,
        render_like_activity,
    )
    from app.services.delivery_service import enqueue_delivery
    from app.services.follow_service import get_follower_inboxes

    is_favourite = emoji == "\u2b50"

    like_activity = render_like_activity(ap_id, actor_uri(actor), note.ap_id, emoji)
    react_activity = None
    if not is_favourite:
        react_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        react_activity = render_emoji_react_activity(
            react_id, actor_uri(actor), note.ap_id, emoji
        )

    # リモートサーバーが表示できるようカスタム絵文字タグを添付
    if is_custom_emoji_shortcode(emoji):
        import re

        sc_match = re.match(r"^:([a-zA-Z0-9_]+)(?:@([a-zA-Z0-9.-]+))?:", emoji)
        if sc_match:
            from app.services.emoji_service import get_custom_emoji

            shortcode = sc_match.group(1)
            domain = sc_match.group(2)

            emoji_obj = await get_custom_emoji(db, shortcode, None)
            if not emoji_obj and domain:
                emoji_obj = await get_custom_emoji(db, shortcode, domain)
            if not emoji_obj and domain:
                from app.services.emoji_service import fetch_and_cache_remote_emoji

                emoji_obj = await fetch_and_cache_remote_emoji(db, shortcode, domain)

            if emoji_obj:
                emoji_tag = [
                    {
                        "id": emoji_obj.url,
                        "type": "Emoji",
                        "name": f":{emoji_obj.shortcode}:",
                        "icon": {
                            "type": "Image",
                            "mediaType": "image/png",
                            "url": emoji_obj.url,
                        },
                    }
                ]
                like_activity["tag"] = emoji_tag
                if react_activity:
                    react_activity["tag"] = emoji_tag

                bare = f":{emoji_obj.shortcode}:"
                like_activity["content"] = bare
                like_activity["_misskey_reaction"] = bare
                if react_activity:
                    react_activity["content"] = bare

    # 配送先inboxを収集: ノート作者 + リアクターのフォロワー
    inboxes: set[str] = set()
    if not note.actor.is_local:
        inboxes.add(note.actor.shared_inbox_url or note.actor.inbox_url)
    follower_inboxes = await get_follower_inboxes(db, actor.id)
    inboxes.update(follower_inboxes)

    from urllib.parse import urlparse

    from app.utils.nodeinfo import ignores_emoji_reactions

    for inbox_url in inboxes:
        domain = urlparse(inbox_url).hostname
        if is_favourite:
            # ☆ favourite → 全サーバーにLikeを送信
            await enqueue_delivery(db, actor.id, inbox_url, like_activity)
        elif domain and await ignores_emoji_reactions(domain):
            # Mastodon → 送信しない (contentを破棄し、常に❤を表示する)
            pass
        else:
            # その他のサーバー → EmojiReact
            await enqueue_delivery(db, actor.id, inbox_url, react_activity)

    return reaction


async def remove_reaction(db: AsyncSession, user: User, note: Note, emoji: str):
    """ノートからリアクションを削除する。"""
    actor = user.actor

    result = await db.execute(
        select(Reaction).where(
            Reaction.actor_id == actor.id,
            Reaction.note_id == note.id,
            Reaction.emoji == emoji,
        )
    )
    reaction = result.scalar_one_or_none()
    if not reaction:
        raise ValueError("Reaction not found")

    reaction_ap_id = reaction.ap_id

    await db.delete(reaction)
    note.reactions_count = max(0, note.reactions_count - 1)
    await db.commit()

    await _publish_reaction_event(db, note)

    # 監視サーバーにUndoを送信 (add_reactionのルーティングと同一)
    if reaction_ap_id:
        from app.activitypub.renderer import (
            render_emoji_react_activity,
            render_like_activity,
            render_undo_activity,
        )
        from app.services.delivery_service import enqueue_delivery
        from app.services.follow_service import get_follower_inboxes

        is_favourite = emoji == "\u2b50"

        like_activity = render_like_activity(
            reaction_ap_id, actor_uri(actor), note.ap_id, emoji
        )
        undo_like_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
        undo_like = render_undo_activity(undo_like_id, actor_uri(actor), like_activity)

        undo_react = None
        if not is_favourite:
            react_activity = render_emoji_react_activity(
                f"{reaction_ap_id}/react", actor_uri(actor), note.ap_id, emoji
            )
            undo_react_id = f"{settings.server_url}/activities/{uuid.uuid4()}"
            undo_react = render_undo_activity(
                undo_react_id, actor_uri(actor), react_activity
            )

        inboxes: set[str] = set()
        if not note.actor.is_local:
            inboxes.add(note.actor.shared_inbox_url or note.actor.inbox_url)
        follower_inboxes = await get_follower_inboxes(db, actor.id)
        inboxes.update(follower_inboxes)

        from urllib.parse import urlparse

        from app.utils.nodeinfo import ignores_emoji_reactions

        for inbox_url in inboxes:
            domain = urlparse(inbox_url).hostname
            if is_favourite:
                # ☆ favourite → 全サーバーにUndo(Like)を送信
                await enqueue_delivery(db, actor.id, inbox_url, undo_like)
            elif domain and await ignores_emoji_reactions(domain):
                # Mastodon → 何も送信していないので、取り消すものもない
                pass
            else:
                # その他のサーバー → Undo(EmojiReact)
                await enqueue_delivery(db, actor.id, inbox_url, undo_react)
