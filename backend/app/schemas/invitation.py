"""招待コードスキーマ。"""

from datetime import datetime

from pydantic import BaseModel, Field


class InvitationCodeCreate(BaseModel):
    max_uses: int | None = Field(1, ge=1, description="最大使用回数 (null = 無制限)")
    expires_in_days: int | None = Field(None, ge=1, le=365, description="N日後に有効期限切れ")


class InvitationCodeResponse(BaseModel):
    code: str
    created_by: str
    used_by: str | None = None
    used_at: datetime | None = None
    max_uses: int | None = 1
    use_count: int = 0
    expires_at: datetime | None = None
    created_at: datetime
