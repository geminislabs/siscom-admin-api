"""
Modelo de Usuario.

Los usuarios pertenecen a una organización (organization_id).
Los permisos se determinan por organization_users.role.

NOTA: El campo is_master está DEPRECADO.
Usar organization_users.role para permisos.

IDENTIDAD POR MARCA (Fase 3, rebanada B)
========================================
Las tres columnas nuevas —`external_id`, `identity_provider` y
`brand_account_id`— las creó la migración `028_identidad_esquema`, desplegada
en producción desde `v1.30.0`. Esto es la mitad *contract* del expand/contract:
modelos encima de columnas que llevan días en la base.

El documento que explica el modelo entero es
`docs/architecture/identidad-y-marca.md`. Lo mínimo para no equivocarse aquí:

- **`external_id` y `cognito_sub` no son lo mismo.** El primero es el *handle*
  (el `Username` con el que se autentica), el segundo el *sujeto* que afirma el
  token (el claim `sub`, que es lo que compara `deps.py`). Ninguno se deduce
  del otro.
- **`external_id` es opaco.** Correo para los usuarios anteriores a esta fase,
  UUID para los que cree la rebanada B2. Un `if "@" in external_id` es un bug.
- **`brand_account_id` NULL significa «la marca por defecto»**, no «sin marca».
- **El correo ya no es único global.** Lo es dentro de una marca. Toda búsqueda
  por correo lleva marca, o es un bug esperando al primer partner.
"""

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, Index, Relationship, SQLModel

if TYPE_CHECKING:
    from app.models.account_user import AccountUser
    from app.models.organization import Organization
    from app.models.organization_user import OrganizationUser
    from app.models.token_confirmacion import TokenConfirmacion


def _handle_por_defecto(context) -> str:
    """El handle de un alta que no trae uno: el correo, igual que el trigger.

    `users_identidad_before` (migración 028) rellena `external_id` con el correo
    cuando el INSERT viene sin él, y por eso la columna es NOT NULL en
    producción aunque ningún código la escriba todavía. El harness de tests
    construye el esquema con `create_all()` y **no tiene triggers**, así que sin
    este default toda alta reventaría contra el NOT NULL.

    Es la misma regla, escrita dos veces a propósito: la de la base sostiene la
    ventana del expand/contract para el código ya desplegado, y ésta hace que
    los tests corran sobre las mismas filas que producción. Ninguna de las dos
    pisa un `external_id` explícito — la rebanada B2 escribirá UUID y ganará.
    """
    return context.get_current_parameters()["email"]


class User(SQLModel, table=True):
    """
    Usuario del sistema.

    Pertenece a una organización y tiene un rol definido en organization_users.
    La autenticación se maneja con AWS Cognito.
    """

    __tablename__ = "users"
    __table_args__ = (
        Index("idx_users_cognito_sub", "cognito_sub"),
        Index("idx_users_organization_master", "organization_id", "is_master"),
        # Los tres índices de la 028. Se declaran aquí para que el harness de
        # tests —que construye el esquema con `create_all()`— tenga la misma
        # unicidad que producción: sin ellos, una prueba de la rebanada B3
        # podría "demostrar" que dos marcas comparten correo sobre una tabla
        # que no lo impide en ningún lado.
        #
        # Son dos y no uno porque `brand_account_id` admite NULL y en Postgres
        # dos NULL nunca chocan: un índice sobre `(brand_account_id, email)` a
        # secas dejaría sin unicidad de correo a todo el padrón actual.
        Index(
            "uq_users_marca_correo",
            "brand_account_id",
            "email",
            unique=True,
            postgresql_where=text("brand_account_id IS NOT NULL"),
        ),
        Index(
            "uq_users_correo_marca_por_defecto",
            "email",
            unique=True,
            postgresql_where=text("brand_account_id IS NULL"),
        ),
        # El handle es único **dentro de su proveedor**, no globalmente: el día
        # que una marca se enrute a otro IdP, nada impide que allí exista un
        # handle que en Cognito ya se use.
        Index(
            "uq_users_proveedor_external_id",
            "identity_provider",
            "external_id",
            unique=True,
        ),
        # Gemela del CHECK que creó la 028. Ampliar la lista es tocar los dos
        # sitios: aquí y `_PROVEEDORES` de la migración.
        CheckConstraint(
            "identity_provider IN ('cognito')",
            name="ck_users_identity_provider",
        ),
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
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
    )
    cognito_sub: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, unique=True, nullable=True, index=True),
    )
    # El correo ya NO es único global: `users_email_key` la quitó la 028. La
    # unicidad vive en los dos índices parciales de `__table_args__`, que la
    # hacen por marca.
    email: str = Field(sa_column=Column(Text, nullable=False))
    # `Optional` en Python y NOT NULL en la base: antes del flush no hay valor,
    # y al insertarlo lo pone `_handle_por_defecto`. Tras el flush la fila
    # siempre tiene handle, en el harness y en producción.
    external_id: Optional[str] = Field(
        default=None,
        sa_column=Column(Text, nullable=False, default=_handle_por_defecto),
    )
    identity_provider: str = Field(
        default="cognito",
        sa_column=Column(Text, nullable=False, server_default=text("'cognito'")),
    )
    # RESTRICT y no CASCADE: borrar una cuenta de marca no puede llevarse por
    # delante credenciales en silencio.
    brand_account_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="RESTRICT"),
            nullable=True,
        ),
    )
    full_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    password_hash: Optional[str] = Field(
        default=None, sa_column=Column(Text, default="", nullable=True)
    )
    email_verified: bool = Field(
        default=False, sa_column=Column(Boolean, default=False, nullable=False)
    )
    # DEPRECADO: Usar organization_users.role
    is_master: bool = Field(
        default=False, sa_column=Column(Boolean, default=False, nullable=True)
    )
    last_login_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime, nullable=True)
    )

    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, server_default=text("now()"), nullable=True),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime, server_default=text("now()"), nullable=True),
    )

    # Relationships
    organization: "Organization" = Relationship(back_populates="users")
    tokens: List["TokenConfirmacion"] = Relationship(back_populates="user")
    organization_memberships: List["OrganizationUser"] = Relationship(
        back_populates="user"
    )
    account_memberships: List["AccountUser"] = Relationship(back_populates="user")

    # Alias para compatibilidad (DEPRECATED)
    @property
    def client_id(self) -> UUID:
        """DEPRECATED: Usar organization_id"""
        return self.organization_id

    @client_id.setter
    def client_id(self, value: UUID):
        """DEPRECATED: Usar organization_id"""
        self.organization_id = value

    # Alias para compatibilidad (DEPRECATED)
    @property
    def client(self) -> "Organization":
        """DEPRECATED: Usar organization"""
        return self.organization

    def get_organization_role(self, organization_id: UUID) -> Optional[str]:
        """
        Obtiene el rol del usuario en una organización específica.

        Args:
            organization_id: ID de la organización

        Returns:
            El rol del usuario o None si no pertenece a la organización
        """
        for membership in self.organization_memberships:
            if membership.organization_id == organization_id:
                return membership.role
        return None
