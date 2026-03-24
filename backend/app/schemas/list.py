from pydantic import BaseModel, Field


class ListCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    replies_policy: str = Field(
        default="list",
        pattern=r"^(none|list|followed)$",
    )
    exclusive: bool = False


class ListUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    replies_policy: str | None = Field(
        default=None,
        pattern=r"^(none|list|followed)$",
    )
    exclusive: bool | None = None


class ListResponse(BaseModel):
    id: str
    title: str
    replies_policy: str
    exclusive: bool


class ListMemberAddRequest(BaseModel):
    account_ids: list[str]
