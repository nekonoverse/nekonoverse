"""連合サーバー情報のクエリサービス。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.actor import Actor
from app.models.delivery import DeliveryJob
from app.models.domain_block import DomainBlock
from app.models.note import Note


async def get_federated_servers(
    db: AsyncSession,
    *,
    limit: int = 40,
    offset: int = 0,
    sort: str = "user_count",
    order: str = "desc",
    search: str | None = None,
    status: str | None = None,
) -> tuple[list[dict], int]:
    """統計情報付きの連合サーバー一覧を集約して返す。

    (servers, total_count) を返す。
    """
    # actorテーブルからドメイン別に集約
    actor_sub = (
        select(
            Actor.domain.label("domain"),
            func.count(Actor.id).label("user_count"),
            func.max(Actor.last_fetched_at).label("last_activity_at"),
            func.min(Actor.created_at).label("first_seen_at"),
        )
        .where(Actor.domain.isnot(None))
        .group_by(Actor.domain)
    )
    if search:
        escaped = search.replace("%", r"\%").replace("_", r"\_")
        actor_sub = actor_sub.where(Actor.domain.ilike(f"%{escaped}%"))

    actor_sub = actor_sub.subquery("actor_agg")

    # noteテーブルからドメイン別の投稿数を集約
    note_sub = (
        select(
            Actor.domain.label("domain"),
            func.count(Note.id).label("note_count"),
        )
        .join(Actor, Note.actor_id == Actor.id)
        .where(Actor.domain.isnot(None), Note.deleted_at.is_(None))
        .group_by(Actor.domain)
        .subquery("note_agg")
    )

    # delivery_queueからドメイン別の配信統計を集約
    # target_inbox_urlからドメインを抽出するためにSQLのsplit_part/substringを使う
    delivery_domain = func.substring(DeliveryJob.target_inbox_url, r"https?://([^/]+)").label(
        "domain"
    )

    delivery_sub = (
        select(
            delivery_domain,
            func.count(DeliveryJob.id).filter(DeliveryJob.status == "delivered").label("d_success"),
            func.count(DeliveryJob.id)
            .filter(DeliveryJob.status.in_(["failed", "processing"]))
            .label("d_failure"),
            func.count(DeliveryJob.id).filter(DeliveryJob.status == "pending").label("d_pending"),
            func.count(DeliveryJob.id).filter(DeliveryJob.status == "dead").label("d_dead"),
        )
        .group_by(delivery_domain)
        .subquery("delivery_agg")
    )

    # メインクエリ: actor集約をベースにJOIN
    query = (
        select(
            actor_sub.c.domain,
            actor_sub.c.user_count,
            actor_sub.c.last_activity_at,
            actor_sub.c.first_seen_at,
            func.coalesce(note_sub.c.note_count, 0).label("note_count"),
            func.coalesce(delivery_sub.c.d_success, 0).label("d_success"),
            func.coalesce(delivery_sub.c.d_failure, 0).label("d_failure"),
            func.coalesce(delivery_sub.c.d_pending, 0).label("d_pending"),
            func.coalesce(delivery_sub.c.d_dead, 0).label("d_dead"),
            DomainBlock.severity.label("block_severity"),
        )
        .outerjoin(note_sub, actor_sub.c.domain == note_sub.c.domain)
        .outerjoin(delivery_sub, actor_sub.c.domain == delivery_sub.c.domain)
        .outerjoin(DomainBlock, actor_sub.c.domain == DomainBlock.domain)
    )

    # ステータスフィルタ
    if status == "suspended":
        query = query.where(DomainBlock.severity == "suspend")
    elif status == "silenced":
        query = query.where(DomainBlock.severity == "silence")
    elif status == "active":
        query = query.where(DomainBlock.id.is_(None))

    # totalカウント
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # ソート
    sort_map = {
        "domain": actor_sub.c.domain,
        "user_count": actor_sub.c.user_count,
        "note_count": func.coalesce(note_sub.c.note_count, 0),
        "last_activity": actor_sub.c.last_activity_at,
    }
    sort_col = sort_map.get(sort, actor_sub.c.user_count)
    if order == "asc":
        query = query.order_by(sort_col.asc().nullslast())
    else:
        query = query.order_by(sort_col.desc().nullsfirst())

    query = query.limit(limit).offset(offset)

    result = await db.execute(query)
    rows = result.all()

    servers = []
    for row in rows:
        block_sev = row.block_severity
        if block_sev == "suspend":
            srv_status = "suspended"
        elif block_sev == "silence":
            srv_status = "silenced"
        else:
            srv_status = "active"

        servers.append(
            {
                "domain": row.domain,
                "user_count": row.user_count,
                "note_count": row.note_count,
                "last_activity_at": row.last_activity_at,
                "first_seen_at": row.first_seen_at,
                "status": srv_status,
                "block_severity": block_sev,
                "delivery_stats": {
                    "success": row.d_success,
                    "failure": row.d_failure,
                    "pending": row.d_pending,
                    "dead": row.d_dead,
                },
            }
        )

    return servers, total


async def get_federated_server_detail(
    db: AsyncSession,
    domain: str,
) -> dict | None:
    """単一の連合サーバーの詳細情報を返す。"""
    # ドメインのactor集約
    actor_agg = await db.execute(
        select(
            func.count(Actor.id).label("user_count"),
            func.max(Actor.last_fetched_at).label("last_activity_at"),
            func.min(Actor.created_at).label("first_seen_at"),
        ).where(Actor.domain == domain)
    )
    agg = actor_agg.one_or_none()
    if not agg or agg.user_count == 0:
        return None

    # ノート数
    note_count_result = await db.execute(
        select(func.count(Note.id))
        .join(Actor, Note.actor_id == Actor.id)
        .where(Actor.domain == domain, Note.deleted_at.is_(None))
    )
    note_count = note_count_result.scalar() or 0

    # 配信統計
    delivery_domain = func.substring(DeliveryJob.target_inbox_url, r"https?://([^/]+)")
    delivery_result = await db.execute(
        select(
            func.count(DeliveryJob.id).filter(DeliveryJob.status == "delivered").label("d_success"),
            func.count(DeliveryJob.id)
            .filter(DeliveryJob.status.in_(["failed", "processing"]))
            .label("d_failure"),
            func.count(DeliveryJob.id).filter(DeliveryJob.status == "pending").label("d_pending"),
            func.count(DeliveryJob.id).filter(DeliveryJob.status == "dead").label("d_dead"),
        ).where(delivery_domain == domain)
    )
    d = delivery_result.one()

    # ドメインブロック情報
    block_result = await db.execute(select(DomainBlock).where(DomainBlock.domain == domain))
    block = block_result.scalar_one_or_none()

    block_sev = block.severity if block else None
    if block_sev == "suspend":
        srv_status = "suspended"
    elif block_sev == "silence":
        srv_status = "silenced"
    else:
        srv_status = "active"

    # 最近のアクター(最大10件)
    actors_result = await db.execute(
        select(Actor)
        .where(Actor.domain == domain)
        .order_by(Actor.last_fetched_at.desc().nullslast())
        .limit(10)
    )
    actors = actors_result.scalars().all()

    return {
        "domain": domain,
        "user_count": agg.user_count,
        "note_count": note_count,
        "last_activity_at": agg.last_activity_at,
        "first_seen_at": agg.first_seen_at,
        "status": srv_status,
        "block_severity": block_sev,
        "block_reason": block.reason if block else None,
        "delivery_stats": {
            "success": d.d_success,
            "failure": d.d_failure,
            "pending": d.d_pending,
            "dead": d.d_dead,
        },
        "recent_actors": [
            {
                "username": a.username,
                "display_name": a.display_name,
                "ap_id": a.ap_id,
                "last_fetched_at": a.last_fetched_at,
            }
            for a in actors
        ],
    }
