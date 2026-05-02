from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ApiKeyCreate(BaseModel):
    product_code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    expires_at: Optional[datetime] = None
    key_metadata: Optional[dict] = None


class ApiKeyUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[str] = Field(None, pattern="^(ACTIVE|REVOKED|EXPIRED)$")


class ApiKeyOut(BaseModel):
    id: UUID
    organization_id: UUID
    product_id: UUID
    name: str
    prefix: str
    status: str
    created_at: Optional[datetime]
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    revoked_at: Optional[datetime]
    key_metadata: Optional[dict]

    model_config = {"from_attributes": True}


class ApiKeyCreated(ApiKeyOut):
    """Returned only once at creation — includes the full plaintext key."""
    full_key: str


class ApiKeyListFilters(BaseModel):
    status: Optional[str] = None
    product_code: Optional[str] = None
