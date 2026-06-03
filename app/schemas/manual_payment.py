from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ManualPaymentCreate(BaseModel):
    account_id: UUID
    organization_id: UUID
    plan_id: UUID
    billing_cycle: Literal["MONTHLY", "YEARLY"] = "MONTHLY"
    active_units: int = Field(default=1, ge=1)
    transaction_ref: Optional[str] = Field(default=None, max_length=200)
    registration_notes: Optional[str] = Field(default=None, max_length=2000)
    operator_email: Optional[str] = Field(default=None, max_length=320)


class ManualPaymentResponse(BaseModel):
    payment_id: UUID
    invoice_id: UUID
    subscription_id: UUID
    amount: str
    currency: str
    billing_cycle: str
    active_units: int
    plan_id: UUID
    organization_id: UUID
