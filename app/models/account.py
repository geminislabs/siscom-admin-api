"""
Modelo de Account - Raíz comercial del cliente.

Account SIEMPRE existe desde el primer registro.
Representa la entidad comercial/billing del cliente.

Modelo Conceptual:
    Account = Raíz comercial (billing, facturación)
    Organization = Raíz operativa (permisos, uso diario)

Relación: Account 1 ──< Organization *

En el onboarding rápido (POST /clients):
    1. Se crea Account (name = account_name del input)
    2. Se crea Organization default (pertenece a Account)
    3. Se crea User master (owner de Organization)
    4. Se registra usuario en Cognito

REGLA DE ORO: Los nombres NO son identidad. Los UUID sí.
Los nombres pueden repetirse; la unicidad está en los UUIDs.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional
from uuid import UUID

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.account_user import AccountUser
    from app.models.organization import Organization


class AccountStatus(str, enum.Enum):
    """
    Estados de una cuenta.

    - ACTIVE: Cuenta activa y operativa
    - SUSPENDED: Cuenta suspendida (falta de pago, violación TOS)
    - DELETED: Eliminación lógica
    """

    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class AccountType(str, enum.Enum):
    """
    Papel de la cuenta en el árbol de reventa (§3 del documento de arquitectura).

    - PLATFORM: la cuenta de Geminis. Es una **etiqueta**, no una raíz sobre las
      demás: nada en el esquema exige que exista, y las marcas son raíces
      independientes. Ver la nota de `account_path`.
    - RESELLER: puede crear subcuentas y administrarlas (reventa delegada).
    - CUSTOMER: cliente final. Es el valor por defecto.

    Es un CHECK en la base y no un tipo ENUM: los ENUM de Postgres solo se
    amplían, y no dentro de una transacción.
    """

    PLATFORM = "PLATFORM"
    RESELLER = "RESELLER"
    CUSTOMER = "CUSTOMER"


class Account(SQLModel, table=True):
    """
    Modelo de Account (tabla: accounts).

    Representa la raíz comercial del cliente.
    Cada Account puede tener múltiples Organizations.

    Responsabilidades:
    - Billing y facturación
    - Agregación comercial
    - Información fiscal y de contacto
    - Auditoría a nivel cuenta (account_events)

    NO gobierna:
    - Permisos operativos (eso es Organization)
    - Dispositivos, unidades, usuarios (eso es Organization)

    NOTA: El campo 'name' puede repetirse entre accounts.
    La unicidad está en el UUID, no en el nombre.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        # Gemelas de los CHECK que creó la 028. Ampliar la lista de proveedores
        # es tocar los dos sitios: aquí y `_PROVEEDORES` de la migración.
        CheckConstraint(
            "identity_provider IS NULL OR identity_provider IN ('cognito')",
            name="ck_accounts_identity_provider",
        ),
        CheckConstraint(
            "jsonb_typeof(idp_config) = 'object'",
            name="ck_accounts_idp_config_objeto",
        ),
    )

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    name: str = Field(sa_column=Column("account_name", Text, nullable=False))
    status: AccountStatus = Field(
        default=AccountStatus.ACTIVE,
        sa_column=Column(Text, default=AccountStatus.ACTIVE.value, nullable=False),
    )
    billing_email: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )

    # ── Árbol de tenancy (migración 027) ─────────────────────────────
    parent_account_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    account_type: AccountType = Field(
        default=AccountType.CUSTOMER,
        sa_column=Column(Text, nullable=False, server_default=text("'CUSTOMER'")),
    )
    account_path: List[UUID] = Field(
        default_factory=list,
        sa_column=Column(ARRAY(PGUUID(as_uuid=True)), nullable=False),
    )
    # ── Enrutamiento de identidad (migración 028) ────────────────────
    # Por cuenta y no por variable de entorno: si el proveedor fuera global,
    # mover a un partner enterprise a WorkOS obligaría a mover a todos.
    # NULL = hereda el proveedor por defecto del despliegue.
    identity_provider: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    # Configuración de la conexión, **nunca credenciales**: lo que va aquí son
    # identificadores y referencias a Secrets Manager. Un secreto en una
    # columna jsonb acaba en cada respaldo, en cada dump de soporte y en cada
    # log de consulta lenta.
    idp_config: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    created_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        )
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        )
    )

    # Relationships
    organizations: List["Organization"] = Relationship(back_populates="account")
    account_users: List["AccountUser"] = Relationship(back_populates="account")

    def es_raiz(self) -> bool:
        """Si la cuenta cuelga de alguien. Cada marca es su propia raíz."""
        return self.parent_account_id is None

    def ancestros(self) -> List[UUID]:
        """
        Los ancestros de la cuenta, del más lejano al más cercano, **sin
        incluirse a sí misma**.

        `account_path` es la cadena completa con la propia cuenta como último
        elemento —lo ancla `ck_accounts_camino_termina_en_si_misma`—, así que
        los ancestros son todo menos el último.
        """
        return list(self.account_path[:-1])

    def get_default_organization(self) -> Optional["Organization"]:
        """
        Obtiene la organización default de la cuenta.

        Por ahora retorna la primera organización.
        En el futuro podría haber un campo `is_default`.
        """
        if self.organizations:
            return self.organizations[0]
        return None
