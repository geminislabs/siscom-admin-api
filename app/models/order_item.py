import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.order import Order


class OrderItemType(str, enum.Enum):
    DEVICE = "DEVICE"
    ACCESSORY = "ACCESSORY"
    SERVICE = "SERVICE"


class OrderItem(SQLModel, table=True):
    __tablename__ = "order_items"
    __table_args__ = (Index("idx_order_items_order", "order_id"),)

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    order_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("orders.id"),
            nullable=False,
        ),
    )
    # device_id ahora referencia a devices.device_id (TEXT) en lugar de devices.id (UUID)
    device_id: Optional[str] = Field(
        default=None,
        sa_column=Column(
            Text, ForeignKey("devices.device_id", ondelete="SET NULL"), nullable=True
        ),
    )
    item_type: OrderItemType = Field(sa_column=Column(String, nullable=False))
    description: str = Field(max_length=500, nullable=False)
    quantity: int = Field(sa_column=Column(Integer, default=1, nullable=False))
    unit_price: Decimal = Field(sa_column=Column(String, nullable=False))
    total_price: Decimal = Field(sa_column=Column(String, nullable=False))

    created_at: datetime = Field(
        sa_column=Column(DateTime, default=utcnow, nullable=False)
    )

    # Relationships
    order: "Order" = Relationship(back_populates="order_items")
