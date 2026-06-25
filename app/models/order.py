import enum
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import Column, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.order_item import OrderItem
    from app.models.organization import Organization


class OrderStatus(str, enum.Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class Order(SQLModel, table=True):
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_organization", "organization_id"),
        Index("idx_orders_status", "status"),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    organization_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("organizations.id"),
            nullable=False,
        ),
    )
    total_amount: Decimal = Field(sa_column=Column(String, nullable=False))
    status: OrderStatus = Field(
        sa_column=Column(String, default=OrderStatus.PENDING.value, nullable=False)
    )
    payment_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
        ),
    )
    shipped_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )

    created_at: datetime = Field(
        sa_column=Column(DateTime, default=utcnow, nullable=False)
    )

    # Relationships
    organization: "Organization" = Relationship(back_populates="orders")
    order_items: List["OrderItem"] = Relationship(back_populates="order")

    # Alias para compatibilidad (DEPRECATED)
    @property
    def client_id(self) -> UUID:
        """DEPRECATED: Usar organization_id"""
        return self.organization_id

    @client_id.setter
    def client_id(self, value: UUID):
        """DEPRECATED: Usar organization_id"""
        self.organization_id = value

    @property
    def client(self) -> "Organization":
        """DEPRECATED: Usar organization"""
        return self.organization
