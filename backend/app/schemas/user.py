import datetime as dt
import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator

# M-6: よく使われるパスワードのブラックリスト
_COMMON_PASSWORDS = frozenset(
    {
        "password",
        "12345678",
        "123456789",
        "1234567890",
        "qwerty123",
        "abcdefgh",
        "password1",
        "iloveyou",
        "sunshine1",
        "princess1",
        "football1",
        "charlie1",
        "access14",
        "master12",
        "dragon12",
        "qwertyui",
        "trustno1",
        "baseball1",
        "letmein1",
        "welcome1",
    }
)


def _validate_password_strength(v: str) -> str:
    """M-6: パスワードの複雑さが十分かを検証する。"""
    # 少なくとも3種類の文字クラスを要求
    classes = 0
    if re.search(r"[a-z]", v):
        classes += 1
    if re.search(r"[A-Z]", v):
        classes += 1
    if re.search(r"[0-9]", v):
        classes += 1
    if re.search(r"[^a-zA-Z0-9]", v):
        classes += 1
    if classes < 2:
        raise ValueError(
            "Password must contain at least 2 types of characters "
            "(lowercase, uppercase, digits, special characters)"
        )
    if v.lower() in _COMMON_PASSWORDS:
        raise ValueError("This password is too common. Please choose a different one.")
    return v


class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=1, max_length=30, pattern=r"^[a-zA-Z0-9_]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    display_name: str | None = None
    invite_code: str | None = None
    reason: str | None = Field(None, max_length=1000)
    captcha_token: str | None = None

    @field_validator("username")
    @classmethod
    def normalize_username(cls, v: str) -> str:
        return v.lower()

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


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

    @field_validator("new_password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        return _validate_password_strength(v)


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
    role: str = "user"
    created_at: datetime

    model_config = {"from_attributes": True}
