import uuid
from datetime import datetime

from pydantic import BaseModel

from app.schemas.note import NoteActorResponse, NoteResponse


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: str
    created_at: datetime
    read: bool
    group_key: str = ""
    account: NoteActorResponse | None = None
    status: NoteResponse | None = None
    emoji: str | None = None
    emoji_url: str | None = None

    model_config = {"from_attributes": True}
