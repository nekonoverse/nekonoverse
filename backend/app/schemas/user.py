import datetime as dt
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None
    invite_code: str | None = None
    reason: str | None = Field(None, max_length=1000)

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.lower()


class UserLoginRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.lower()

    password: str


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(None, max_length=255)


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


class FocalPoint(BaseModel):
    x: float
    y: float


class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    display_name: str | None
    avatar_url: str | None
    header_url: str | None
    avatar_focal: FocalPoint | None = None
    header_focal: FocalPoint | None = None
    summary: str | None
    fields: list[dict] = []
    birthday: dt.date | None = None
    is_cat: bool = False
    is_bot: bool = False
    locked: bool = False
    discoverable: bool = True
    role: str = "user"
    created_at: datetime

    model_config = {"from_attributes": True}
