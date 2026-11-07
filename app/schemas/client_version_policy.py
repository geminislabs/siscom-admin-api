from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ClientVersionPolicyOut(BaseModel):
    """Una fila de `client_version_policy`, tal como la ve GAC."""

    model_config = ConfigDict(from_attributes=True)

    platform: str
    min_supported_version: Optional[str] = None
    latest_version: Optional[str] = None
    blocked_versions: List[str] = Field(default_factory=list)
    store_url: Optional[str] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


class ClientVersionPolicyIn(BaseModel):
    """La fila entera: los cuatro campos siempre presentes (`null` vale)."""

    model_config = ConfigDict(extra="forbid")

    min_supported_version: Optional[str] = Field(..., max_length=64)
    latest_version: Optional[str] = Field(..., max_length=64)
    blocked_versions: List[str] = Field(...)
    store_url: Optional[str] = Field(..., max_length=2048)


class InstallsVersion(BaseModel):
    app_version: str
    installs: int


class InstallsOut(BaseModel):
    platform: str
    days: int
    total: int
    versions: List[InstallsVersion]


class PreviewVersion(InstallsVersion):
    update: Literal["none", "optional", "required"]


class PreviewOut(BaseModel):
    platform: str
    days: int
    total: int
    required: int
    optional: int
    versions: List[PreviewVersion]
