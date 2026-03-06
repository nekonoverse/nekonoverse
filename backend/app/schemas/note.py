import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class NoteCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    visibility: str = Field(default="public", pattern=r"^(public|unlisted|followers|direct)$")
    sensitive: bool = False
    spoiler_text: str | None = None
    in_reply_to_id: uuid.UUID | None = None
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    quote_id: uuid.UUID | None = None


class NoteActorResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None
    avatar_url: str | None
    ap_id: str
    domain: str | None

    model_config = {"from_attributes": True}


class ReactionSummary(BaseModel):
    emoji: str
    count: int
    me: bool = False


class NoteMediaAttachment(BaseModel):
    id: str
    type: str
    url: str
    preview_url: str
    description: str | None = None
    blurhash: str | None = None
    meta: dict | None = None


class NoteResponse(BaseModel):
    id: uuid.UUID
    ap_id: str
    content: str
    source: str | None
    visibility: str
    sensitive: bool
    spoiler_text: str | None
    published: datetime
    replies_count: int
    reactions_count: int
    renotes_count: int
    actor: NoteActorResponse
    reactions: list[ReactionSummary] = []
    reblog: "NoteResponse | None" = None
    media_attachments: list[NoteMediaAttachment] = []
    quote: "NoteResponse | None" = None

    model_config = {"from_attributes": True}
