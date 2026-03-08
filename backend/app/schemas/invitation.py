"""Invitation code schemas."""

from datetime import datetime

from pydantic import BaseModel


class InvitationCodeResponse(BaseModel):
    code: str
    created_by: str
    used_by: str | None = None
    used_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
