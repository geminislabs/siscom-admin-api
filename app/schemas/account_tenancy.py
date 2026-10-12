"""
Schemas de los endpoints internos con los que GAC convierte una cuenta en marca
(B4, rebanada 4).

Solo los usa el plano de control (`/internal/accounts/...`, token PASETO de
GAC). Ningún cliente de Nexus escribe el tipo de cuenta ni sus capabilities.
"""

from datetime import datetime
from typing import Literal, Optional, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# PLATFORM no está: es la etiqueta de la cuenta de Geminis y no se asigna ni se
# quita por API. Ver `AccountType`.
TipoAsignable = Literal["RESELLER", "CUSTOMER"]

ValorDeCapability = Union[bool, int, str]


class AccountTypeUpdate(BaseModel):
    """`PATCH /internal/accounts/{id}`: el papel de la cuenta en el árbol."""

    model_config = ConfigDict(extra="forbid")

    account_type: TipoAsignable = Field(
        ...,
        description="RESELLER convierte la cuenta en marca; CUSTOMER la regresa",
    )


class AccountTypeOut(BaseModel):
    id: UUID
    account_name: str
    account_type: str
    parent_account_id: Optional[UUID] = None
    changed: bool = Field(
        ..., description="False si la cuenta ya tenía ese tipo (no se auditó nada)"
    )


class AccountCapabilityIn(BaseModel):
    """`PUT /internal/accounts/{id}/capabilities/{code}`."""

    model_config = ConfigDict(extra="forbid")

    value: ValorDeCapability = Field(
        ..., description="Del tipo de la capability: bool, int o texto"
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Por qué se concede o se limita; queda en la fila y en la auditoría",
    )
    expires_at: Optional[datetime] = Field(
        default=None,
        description="Sin fecha, no caduca. Caducada, la fila deja de contar",
    )


class AccountCapabilityOut(BaseModel):
    """Una capability comercial de la cuenta: lo que tiene ella y lo que vale."""

    code: str
    value_type: str
    description: Optional[str] = None
    own_value: Optional[ValorDeCapability] = Field(
        default=None,
        description="El valor de la fila de esta cuenta, o null si no tiene fila",
    )
    reason: Optional[str] = None
    expires_at: Optional[datetime] = None
    expired: bool = False
    effective_value: Optional[ValorDeCapability] = Field(
        default=None,
        description="El valor que rige, ya recortado por los ancestros",
    )
    source: str = Field(..., description="'cuenta', 'ancestro' o 'default'")
    limited_by: Optional[UUID] = Field(
        default=None,
        description="El ancestro cuyo techo recortó el valor propio, si alguno lo hizo",
    )
