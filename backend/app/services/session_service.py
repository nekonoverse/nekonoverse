import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.login_history import LoginHistory

SESSION_TTL = 86400 * 30  # 30 days


async def create_session_with_metadata(
    valkey,
    user_id: uuid.UUID,
    session_id: str,
    ip: str,
    user_agent: str | None,
) -> None:
    """セッションキーを作成し、メタデータと共に保存する。"""
    await valkey.set(f"session:{session_id}", str(user_id), ex=SESSION_TTL)
    await valkey.hset(
        f"session_meta:{session_id}",
        mapping={
            "user_id": str(user_id),
            "ip": ip,
            "user_agent": user_agent or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    await valkey.expire(f"session_meta:{session_id}", SESSION_TTL)
    await valkey.sadd(f"user_sessions:{user_id}", session_id)


async def list_user_sessions(valkey, user_id: uuid.UUID) -> list[dict]:
    """ユーザーのアクティブセッション一覧を返す。期限切れのものは削除する。"""
    session_ids = await valkey.smembers(f"user_sessions:{user_id}")
    sessions = []
    for sid in session_ids:
        if not await valkey.exists(f"session:{sid}"):
            await valkey.srem(f"user_sessions:{user_id}", sid)
            await valkey.delete(f"session_meta:{sid}")
            continue
        meta = await valkey.hgetall(f"session_meta:{sid}")
        sessions.append({"session_id": sid, **meta})
    return sessions


async def delete_session(
    valkey, user_id: uuid.UUID, session_id: str
) -> bool:
    """ユーザーに属する特定のセッションを削除する。所有者でない場合はFalseを返す。"""
    owner = await valkey.get(f"session:{session_id}")
    if owner != str(user_id):
        return False
    await valkey.delete(f"session:{session_id}")
    await valkey.delete(f"session_meta:{session_id}")
    await valkey.srem(f"user_sessions:{user_id}", session_id)
    return True


async def cleanup_session_metadata(
    valkey, user_id: uuid.UUID, session_id: str
) -> None:
    """セッションのメタデータキーをクリーンアップする (ログアウト/無効化時に使用)。"""
    await valkey.delete(f"session_meta:{session_id}")
    await valkey.srem(f"user_sessions:{user_id}", session_id)


async def record_login(
    db: AsyncSession,
    user_id: uuid.UUID,
    ip: str,
    user_agent: str | None,
    method: str,
    success: bool = True,
) -> None:
    """ログイン試行をデータベースに記録する。"""
    entry = LoginHistory(
        user_id=user_id,
        ip_address=ip,
        user_agent=user_agent,
        method=method,
        success=success,
    )
    db.add(entry)
    await db.flush()


async def get_login_history(
    db: AsyncSession,
    user_id: uuid.UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[LoginHistory]:
    """ユーザーのログイン履歴を新しい順に返す。"""
    result = await db.execute(
        select(LoginHistory)
        .where(LoginHistory.user_id == user_id)
        .order_by(LoginHistory.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    return list(result.scalars().all())
