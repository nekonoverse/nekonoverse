import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class PollCreateRequest(BaseModel):
    options: list[str] = Field(min_length=2, max_length=10)
    expires_in: int = Field(default=86400, ge=300, le=2592000)  # seconds
    multiple: bool = False


class NoteCreateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    visibility: str = Field(default="public", pattern=r"^(public|unlisted|followers|direct)$")
    sensitive: bool = False
    spoiler_text: str | None = Field(default=None, max_length=500)
    in_reply_to_id: uuid.UUID | None = None
    media_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)
    quote_id: uuid.UUID | None = None
    poll: PollCreateRequest | None = None


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
    emoji_url: str | None = None


class CustomEmojiInfo(BaseModel):
    shortcode: str
    url: str
    static_url: str


class NoteMediaAttachment(BaseModel):
    id: str
    type: str
    url: str
    preview_url: str
    description: str | None = None
    blurhash: str | None = None
    meta: dict | None = None


class PollOptionResponse(BaseModel):
    title: str
    votes_count: int = 0


class PollResponse(BaseModel):
    id: str
    expires_at: str | None = None
    expired: bool = False
    multiple: bool = False
    votes_count: int = 0
    voters_count: int = 0
    options: list[PollOptionResponse] = []
    voted: bool = False
    own_votes: list[int] = []


class TagInfo(BaseModel):
    name: str
    url: str


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
    in_reply_to_id: uuid.UUID | None = None
    in_reply_to_account_id: uuid.UUID | None = None
    actor: NoteActorResponse
    reactions: list[ReactionSummary] = []
    reblog: "NoteResponse | None" = None
    media_attachments: list[NoteMediaAttachment] = []
    quote: "NoteResponse | None" = None
    poll: PollResponse | None = None
    pinned: bool = False
    emojis: list[CustomEmojiInfo] = []
    tags: list[TagInfo] = []

    model_config = {"from_attributes": True}


class ContextResponse(BaseModel):
    ancestors: list[NoteResponse] = []
    descendants: list[NoteResponse] = []
