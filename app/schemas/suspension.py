"""El estado de acceso de una organización, tal como lo ven los clientes.

Mismos campos que el cuerpo del 403 de `OrganizacionNoDisponible`
(`app/api/deps.py`), para que un cliente pinte la pantalla de suspensión
igual venga de `/auth/me` o de un 403 a mitad de sesión.
"""

from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class AccessBlockedOut(BaseModel):
    """Por qué la organización no da acceso. Ver `app/services/suspension.py`."""

    error_code: Literal["organization_suspended", "organization_deleted"]
    suspended_by: Literal["organization", "account"] = Field(
        ...,
        description=(
            "Si se suspendió la organización misma o la cuenta de facturación "
            "a la que pertenece (que apaga todas sus organizaciones)."
        ),
    )
    can_manage_billing: bool = Field(
        ...,
        description=(
            "Si esta persona puede entrar a facturación para pagar y "
            "reactivarla: owner o billing, y sólo si está suspendida, no borrada."
        ),
    )


def bloqueo_a_salida(bloqueo, rol) -> "AccessBlockedOut | None":
    from app.services import suspension

    if bloqueo is None:
        return None
    return AccessBlockedOut(
        error_code=bloqueo.error_code,
        suspended_by=bloqueo.origen,
        can_manage_billing=(
            bloqueo.es_suspension and suspension.puede_administrar_facturacion(rol)
        ),
    )


class AccountStatusUpdate(BaseModel):
    """Cuerpo de `PATCH /internal/accounts/{account_id}/status`."""

    status: Literal["ACTIVE", "SUSPENDED"] = Field(
        ...,
        description=(
            "Borrar una cuenta no se hace aquí: `DELETED` no tiene vuelta desde "
            "este endpoint."
        ),
    )
    include_subaccounts: bool = Field(
        default=False,
        description=(
            "Sólo para una marca (`RESELLER`): aplica el mismo cambio a todas "
            "sus subcuentas, en todo el árbol. Sin esto, suspender una marca no "
            "toca a sus clientes."
        ),
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Motivo, para la auditoría (`account_events`).",
    )
    cause: Literal["non_payment", "other"] = Field(
        default="non_payment",
        description=(
            "Por qué se suspende. `non_payment`: un pago exitoso la reactiva sola "
            "(`app/services/suspension.py`). `other` (abuso, fraude…): sólo se "
            "reactiva desde GAC. Se ignora al reactivar."
        ),
    )


class AccountStatusChange(BaseModel):
    id: UUID
    account_name: str
    previous_status: str
    status: str


class AccountStatusOut(BaseModel):
    """Lo que cambió. `subaccounts` sólo trae las que cambiaron de verdad."""

    account: AccountStatusChange
    changed: bool
    subaccounts: list[AccountStatusChange] = Field(default_factory=list)
