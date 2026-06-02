import uuid

from pydantic import BaseModel

from app.schemas.note import NoteActorResponse, NoteResponse


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: str
    # サーバ内部の生 type (Mastodon 標準にない quote / reaction を区別したい自家
    # クライアント向け)。type は Mastodon 互換のためマッピング後 (quote→reblog,
    # reaction→favourite 等) を返すが、こちらは notification 行に格納された生値。
    # Pleroma の pleroma.notification_type に相当する nekonoverse 拡張フィールド。
    nekonoverse_type: str | None = None
    created_at: str
    read: bool
    group_key: str = ""
    account: NoteActorResponse | None = None
    status: NoteResponse | None = None
    emoji: str | None = None
    emoji_url: str | None = None

    model_config = {"from_attributes": True}
