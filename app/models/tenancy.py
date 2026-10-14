"""
Modelos del árbol de tenancy — Fase 2, rebanada B.

Ponen modelos SQLModel encima de lo que creó la migración `027_tenancy_esquema`
(rebanada A). El esquema ya está en producción desde `v1.28.0`; esto es la mitad
*contract* del expand/contract: código que empieza a usar columnas que llevan
días ahí.

QUÉ HAY AQUÍ
============
  TenantDomain    hostname -> cuenta de marca. Resuelve apariencia, NUNCA autoriza
  TenantBranding  borrador y publicado del tema por tenant

`AccountCapability` vive en `capability.py`, junto a sus hermanas
`PlanCapability` y `OrganizationCapability`: es el mismo motor, en otro nivel.

LO QUE ESTOS MODELOS NO HACEN
=============================
`accounts.account_path` lo mantienen dos triggers en la base, no la aplicación.
El modelo lo declara para poder leerlo y consultarlo, pero **escribirlo desde
aquí no tiene efecto**: el trigger `BEFORE` lo recalcula desde el camino del
padre e ignora lo que traiga el INSERT. Es deliberado — ese camino es el
predicado de aislamiento entre clientes y no puede vivir en una capa que se
salta con un script de soporte. Para mover una cuenta de sitio se cambia
`parent_account_id` y el trigger `AFTER` propaga a los descendientes.
"""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel


class TenantDomain(SQLModel, table=True):
    """
    Un hostname y la cuenta de marca a la que pertenece (tabla: tenant_domains).

    `hostname` es UNIQUE **global**, no por cuenta: si dos marcas reclamaran el
    mismo `Host`, quien resuelve tendría que elegir, y esa es una decisión que
    no debería existir. Se guarda en minúsculas por restricción de la base, de
    modo que la búsqueda sea una igualdad indexable y no un `lower()`.

    ADVERTENCIA, y es la que más errores previene en estas plataformas: el
    `Host` de una petición llega en la caja que mande el cliente. Resuelve
    **apariencia** —logo, colores, textos legales— y nunca datos. Que alguien
    mande `Host: meromero.com` a mano no le da acceso a nada.
    """

    __tablename__ = "tenant_domains"

    id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            primary_key=True,
            server_default=text("gen_random_uuid()"),
        )
    )
    account_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="CASCADE"),
            nullable=False,
        )
    )
    hostname: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    is_primary: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("false")),
    )
    status: str = Field(
        default="PENDING",
        sa_column=Column(Text, nullable=False, server_default=text("'PENDING'")),
    )
    verification_token: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    verified_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )

    def esta_verificado(self) -> bool:
        """
        Si este dominio puede servir la marca.

        La base ya impone que `status = 'VERIFIED'` y `verified_at IS NOT NULL`
        vayan juntos, así que basta mirar el estado.
        """
        return self.status == "VERIFIED"


class TenantBranding(SQLModel, table=True):
    """
    Tema de una marca, en dos juegos (tabla: tenant_branding).

    `published` es lo que ve el mundo; `draft` es lo que el partner está
    editando y todavía no publica. Separarlos desde el principio es barato — y
    molesto después, porque implica reescribir cada lectura.

    Los tokens van en `jsonb` y no en columnas porque el juego de tokens va a
    cambiar durante la Fase 4, y una columna por token significa una migración
    por token. La validación —contraste WCAG AA, saneado de assets— es de
    aplicación, no de esquema.
    """

    __tablename__ = "tenant_branding"

    account_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey("accounts.id", ondelete="CASCADE"),
            primary_key=True,
        )
    )
    brand_name: Optional[str] = Field(
        default=None, sa_column=Column(Text, nullable=True)
    )
    published: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(JSONB, nullable=False, server_default=text("'{}'::jsonb")),
    )
    # `none_as_null`: sin él, `draft = None` se escribe como el JSON `'null'`,
    # no como NULL de SQL, y `ck_tenant_branding_draft_objeto` lo rechaza. Así
    # publicar y descartar respondían 500 en producción (13/10/2026).
    draft: Optional[dict[str, Any]] = Field(
        default=None, sa_column=Column(JSONB(none_as_null=True), nullable=True)
    )
    published_at: Optional[datetime] = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    published_by: Optional[UUID] = Field(
        default=None,
        sa_column=Column(PGUUID(as_uuid=True), ForeignKey("users.id"), nullable=True),
    )
    created_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )
    updated_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(
            DateTime(timezone=True), server_default=text("now()"), nullable=False
        ),
    )
