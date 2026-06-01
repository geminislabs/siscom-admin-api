# app/schemas/payment.py
from datetime import datetime
from decimal import Decimal
from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from app.models.payment import PaymentStatus


class PaymentBase(BaseModel):
    amount: Decimal
    currency: str = "MXN"
    method: Optional[str] = None


class PaymentCreate(PaymentBase):
    pass


class PaymentOut(PaymentBase):
    id: UUID
    account_id: UUID
    paid_at: Optional[datetime] = None
    status: PaymentStatus
    transaction_ref: Optional[str] = None
    invoice_url: Optional[str] = None
    gateway: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True
        json_schema_extra = {
            "example": {
                "id": "123e4567-e89b-12d3-a456-426614174000",
                "account_id": "223e4567-e89b-12d3-a456-426614174000",
                "amount": "299.00",
                "currency": "MXN",
                "method": "card",
                "paid_at": "2024-01-15T10:30:00Z",
                "status": "SUCCESS",
                "transaction_ref": "pi_abc123xyz",
                "invoice_url": None,
                "gateway": "stripe",
                "created_at": "2024-01-15T10:30:00Z",
            }
        }