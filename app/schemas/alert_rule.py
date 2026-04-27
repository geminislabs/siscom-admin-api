from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AlertRuleBase(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    type: str = Field(..., min_length=1, max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)


class AlertRuleCreate(AlertRuleBase):
    unit_ids: Optional[list[UUID]] = None


class AlertRuleUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    type: Optional[str] = Field(None, min_length=1, max_length=120)
    config: Optional[dict[str, Any]] = None
    unit_ids: Optional[list[UUID]] = None


class AlertRuleUnitsAssign(BaseModel):
    unit_ids: list[UUID] = Field(..., min_length=1)


class AlertRuleUnitsUnassign(BaseModel):
    unit_ids: list[UUID] = Field(..., min_length=1)


class AlertRuleOut(AlertRuleBase):
    id: UUID
    organization_id: UUID
    created_by: Optional[UUID] = None
    unit_ids: list[UUID] = Field(default_factory=list)
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AlertRuleDeleteOut(BaseModel):
    message: str
    rule_id: UUID
    deleted: bool


class AlertRuleUnitsOut(BaseModel):
    rule_id: UUID
    unit_ids: list[UUID]
