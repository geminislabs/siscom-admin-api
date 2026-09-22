"""Esquemas de la superficie interna de usuarios (GAC).

Son deliberadamente distintos de `UserOut`: esta superficie la consume GAC,
que resuelve casos que Nexus no alcanza —los huérfanos, sobre todo— y necesita
ver cosas que a un admin de organización no le importan, como si su
organización existe.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.user import UserStatus


class InternalUserOut(BaseModel):
    """Un usuario visto desde el plano de control."""

    id: UUID
    email: str
    full_name: Optional[str] = None
    status: str
    organization_id: Optional[UUID] = None
    # **La razón de ser de este campo**: `users.organization_id` no tiene clave
    # foránea en producción, así que puede apuntar a una organización que no
    # existe. Al 21/09/2026 son siete de veintitrés usuarios. Sin este booleano,
    # GAC no puede distinguir a un usuario normal de uno huérfano sin consultar
    # otra tabla — y son justo los que no puede tocar por la vía de Nexus.
    huerfano: bool = Field(
        description="Su organization_id apunta a una organización que no existe"
    )
    is_master: bool = False
    email_verified: bool = False
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class InternalUserStatusIn(BaseModel):
    """El cambio de estado que pide GAC."""

    status: UserStatus = Field(
        description="ACTIVE o INACTIVE. La lista la fija `ck_users_status`."
    )
    motivo: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Por qué se cambia. Va al log; no se guarda en la fila.",
    )


class InternalUserStatusOut(BaseModel):
    """Lo que devuelve el cambio, incluido lo que NO se pudo hacer."""

    id: UUID
    email: str
    status: str
    # Se informa de si el refuerzo en el proveedor salió bien, **sin que su
    # fallo tumbe la operación**: la fuente de verdad es `users.status`, ya
    # escrito. Devolverlo en vez de tragárselo es lo que permite a GAC enseñar
    # "desactivado, pero la credencial sigue viva" en vez de mentir.
    proveedor_sincronizado: bool
    detalle: Optional[str] = None
