"""
Modelos del catálogo de permisos y de los roles (D6 de B4).

Los endpoints preguntan por **permiso** (`branding.write`) y no por nombre de
rol. Hoy los roles son los cuatro de sistema —owner, admin, billing, member—,
uno por alcance; cuando lleguen los roles personalizados serán filas de `roles`
con `account_id`, y ningún endpoint tendrá que cambiar. La justificación y lo
que la base garantiza por sí sola están en la migración 038.

Basado en DDL:
- public.permissions
- public.roles
- public.role_permissions
"""

import enum
from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, SQLModel


class PermissionScope(str, enum.Enum):
    """
    Contra qué membresía se verifica un permiso.

    - account: lo comercial (marca, plan, facturación, subcuentas); se verifica
      contra `account_users.role`.
    - organization: lo operativo (unidades, dispositivos, usuarios, zonas); se
      verifica contra `organization_users.role` de la organización activa.
    """

    ACCOUNT = "account"
    ORGANIZATION = "organization"


class Permission(SQLModel, table=True):
    """Un permiso del catálogo. Sus filas nacen de migraciones, nunca de la UI."""

    __tablename__ = "permissions"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('account', 'organization')", name="ck_permissions_scope"
        ),
        CheckConstraint(
            "code ~ '^[a-z][a-z_]*\\.[a-z][a-z_]*$'",
            name="ck_permissions_code_formato",
        ),
        UniqueConstraint("code", "scope", name="uq_permissions_code_scope"),
    )

    code: str = Field(sa_column=Column(Text, primary_key=True))
    description: str = Field(sa_column=Column(Text, nullable=False))
    scope: str = Field(sa_column=Column(Text, nullable=False))
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )


class Role(SQLModel, table=True):
    """
    Un rol. Los de sistema (`is_system`, sin `account_id`) no se editan; los
    personalizados siempre pertenecen a una cuenta.
    """

    __tablename__ = "roles"
    __table_args__ = (
        CheckConstraint("scope IN ('account', 'organization')", name="ck_roles_scope"),
        CheckConstraint(
            "is_system = (account_id IS NULL)", name="ck_roles_sistema_sin_cuenta"
        ),
        UniqueConstraint("id", "scope", name="uq_roles_id_scope"),
        Index(
            "uq_roles_de_sistema",
            "scope",
            "code",
            unique=True,
            postgresql_where=text("account_id IS NULL"),
        ),
        Index(
            "uq_roles_de_cuenta",
            "account_id",
            "scope",
            "code",
            unique=True,
            postgresql_where=text("account_id IS NOT NULL"),
        ),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    scope: str = Field(sa_column=Column(Text, nullable=False))
    code: str = Field(sa_column=Column(Text, nullable=False))
    name: str = Field(sa_column=Column(Text, nullable=False))
    account_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=True,
        ),
    )
    is_system: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )


class RolePermission(SQLModel, table=True):
    """
    Qué permisos tiene cada rol.

    `scope` repite el del rol y el del permiso a propósito: en la base, dos FK
    compuestas lo atan a ambos para que un rol de cuenta no reciba un permiso de
    organización. Aquí solo se declaran las FK simples, que son las que compara
    `scripts/verificar-deriva.py`.
    """

    __tablename__ = "role_permissions"
    __table_args__ = (Index("ix_role_permissions_permission_code", "permission_code"),)

    role_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("roles.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    permission_code: str = Field(
        sa_column=Column(
            Text,
            ForeignKey("permissions.code", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    scope: str = Field(sa_column=Column(Text, nullable=False))
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )
