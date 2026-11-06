from datetime import datetime
from typing import TYPE_CHECKING, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, ForeignKey, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.unit import Unit
    from app.models.user import User


class UserUnit(SQLModel, table=True):
    """
    Permisos de usuarios sobre unidades.
    Define qué usuarios pueden ver/editar/administrar qué unidades.
    """

    __tablename__ = "user_units"
    __table_args__ = (
        UniqueConstraint("user_id", "unit_id", name="uq_user_units_user_unit"),
        # Nota: check_user_units_role se crea en la migración SQL
        Index("idx_user_units_user_id", "user_id"),
        Index("idx_user_units_unit_id", "unit_id"),
        Index("idx_user_units_role", "role"),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )

    user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )

    unit_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("units.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )

    granted_by: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )

    granted_at: datetime = Field(
        sa_column=Column(TIMESTAMP(timezone=True), server_default=text("now()"))
    )

    role: str = Field(
        default="viewer",
        sa_column=Column(Text, server_default="viewer", nullable=False),
    )

    # Sin esto la concesión sólo da lo ocurrido desde `granted_at` (046). Quien
    # concede tiene que pedir explícitamente que se vea el pasado de la unidad.
    include_history: bool = Field(
        default=False,
        sa_column=Column(Boolean, server_default=text("false"), nullable=False),
    )

    # Relationships
    user: "User" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[UserUnit.user_id]"}
    )
    unit: "Unit" = Relationship(back_populates="user_units")
    granted_by_user: Optional["User"] = Relationship(
        sa_relationship_kwargs={
            "foreign_keys": "[UserUnit.granted_by]",
            "lazy": "joined",
        }
    )


class UserUnitGrantHistory(SQLModel, table=True):
    """
    Concesiones de `user_units` ya retiradas, con la ventana en que valieron.

    La llena el trigger `trg_archivar_concesion_retirada` al borrar de
    `user_units` (migración 046); el código no escribe aquí. Sin claves
    foráneas a propósito: ver el docstring de la migración.
    """

    __tablename__ = "user_unit_grants_history"
    __table_args__ = (
        Index("idx_user_unit_grants_history_user_unit", "user_id", "unit_id"),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    user_id: UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))
    unit_id: UUID = Field(sa_column=Column(PGUUID(as_uuid=True), nullable=False))
    granted_by: Optional[UUID] = Field(
        default=None, sa_column=Column(PGUUID(as_uuid=True), nullable=True)
    )
    granted_at: Optional[datetime] = Field(
        default=None, sa_column=Column(TIMESTAMP(timezone=True), nullable=True)
    )
    revoked_at: datetime = Field(
        sa_column=Column(
            TIMESTAMP(timezone=True), server_default=text("now()"), nullable=False
        )
    )
    role: str = Field(sa_column=Column(Text, nullable=False))
    include_history: bool = Field(sa_column=Column(Boolean, nullable=False))
