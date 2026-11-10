"""Suspensión de organizaciones y cuentas: la regla, en un solo sitio.

LA REGLA
========
Una organización está **suspendida** si lo está ella (`organizations.status`)
o si lo está la cuenta a la que pertenece (`accounts.status`): la cuenta es la
raíz de facturación, y suspenderla apaga todas sus organizaciones. No hay
cascada hacia abajo en el árbol de reventa: suspender una marca no suspende a
sus clientes, que son cuentas propias con su propio `status`. GAC puede
suspenderlos también, pero tiene que pedirlo explícitamente
(`PATCH /internal/accounts/{id}/status` con `include_subaccounts`).

La regla mira la organización **en la que se actúa**, no a la persona. Quien
está invitado a una organización ajena sigue entrando en ella aunque su propia
cuenta esté suspendida, y al revés: el invitado de una organización suspendida
no entra en ella, pero sí en las suyas.

Una organización o cuenta `DELETED` tampoco da acceso, y en ese caso no hay
excepción para facturación.

QUIÉN LA APLICA
===============
`app/api/deps.py`, en cada camino que resuelve la organización de una sesión
de Cognito (`_load_current_user` y las fábricas que no pasan por ella). Las
excepciones —facturación para quien la administra, `/auth/me`,
`/auth/organizations`— se declaran allí, en la dependencia del endpoint.

La revocación de data tokens y enlaces compartidos al suspender la hace
`app/services/session_revocation.py` desde el ORM, como el resto de lo que
estrecha permisos.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from uuid import UUID

from sqlalchemy.orm import Session

ORGANIZATION_SUSPENDED = "organization_suspended"
ORGANIZATION_DELETED = "organization_deleted"

Origen = Literal["organization", "account"]


@dataclass(frozen=True)
class Bloqueo:
    """Por qué una organización no da acceso."""

    error_code: str
    origen: Origen

    @property
    def es_suspension(self) -> bool:
        return self.error_code == ORGANIZATION_SUSPENDED


def _valor(estado) -> Optional[str]:
    return getattr(estado, "value", estado)


def bloqueo_de(db: Session, organization_id: Optional[UUID]) -> Optional[Bloqueo]:
    """
    `None` si la organización da acceso; si no, por qué.

    Borrado gana a suspendido, y la organización gana a la cuenta: es el motivo
    más específico el que se le cuenta al cliente.
    """
    from app.models.account import Account, AccountStatus
    from app.models.organization import Organization, OrganizationStatus

    if organization_id is None:
        return None

    fila = (
        db.query(Organization.status, Account.status)
        .join(Account, Account.id == Organization.account_id)
        .filter(Organization.id == organization_id)
        .first()
    )
    if fila is None:
        return None
    estado_org, estado_cuenta = (_valor(e) for e in fila)

    if estado_org == OrganizationStatus.DELETED.value:
        return Bloqueo(ORGANIZATION_DELETED, "organization")
    if estado_cuenta == AccountStatus.DELETED.value:
        return Bloqueo(ORGANIZATION_DELETED, "account")
    if estado_org == OrganizationStatus.SUSPENDED.value:
        return Bloqueo(ORGANIZATION_SUSPENDED, "organization")
    if estado_cuenta == AccountStatus.SUSPENDED.value:
        return Bloqueo(ORGANIZATION_SUSPENDED, "account")
    return None


def puede_administrar_facturacion(rol: Optional[str]) -> bool:
    """Quién puede seguir pagando en una organización suspendida."""
    from app.models.organization_user import OrganizationRole

    return rol in (OrganizationRole.OWNER.value, OrganizationRole.BILLING.value)


def descendientes(db: Session, account_id: UUID) -> list:
    """Las subcuentas de una cuenta en todo su árbol, sin incluirla a ella."""
    from app.models.account import Account

    return (
        db.query(Account)
        .filter(Account.account_path.any(account_id), Account.id != account_id)
        .all()
    )


# ---------------------------------------------------------------------------
# Reactivar al pagar
# ---------------------------------------------------------------------------
#
# Quien suspende (GAC) dice por qué: `non_payment` (el valor por defecto) u
# `other` (abuso, fraude, una petición del cliente…). La causa queda en la
# auditoría, en el evento de la suspensión, y es lo único que mira el pago:
# un pago exitoso reactiva lo que se suspendió por falta de pago y deja como
# está lo demás, que sólo se reactiva desde GAC.

CAUSA_FALTA_DE_PAGO = "non_payment"
CAUSA_OTRA = "other"
Causa = Literal["non_payment", "other"]


def _ultima_suspension(db: Session, event_type: str, target_id: UUID) -> Optional[dict]:
    """Los metadatos del último cambio de estado, si fue una suspensión."""
    from app.models.account_event import AccountEvent

    evento = (
        db.query(AccountEvent)
        .filter(
            AccountEvent.event_type == event_type,
            AccountEvent.target_id == target_id,
        )
        .order_by(AccountEvent.created_at.desc())
        .first()
    )
    meta = (evento.event_metadata or {}) if evento is not None else None
    if meta is None or meta.get("nuevo") != "SUSPENDED":
        return None
    return meta


def _se_reactiva_al_pagar(
    meta: Optional[dict], via_reseller: Optional[UUID] = None
) -> bool:
    """
    Si una suspensión se levanta con un pago.

    Sin registro (se suspendió antes de que hubiera causa, o a mano en la base)
    se trata como falta de pago, que es el caso común; sólo para la cuenta
    misma, nunca para una subcuenta, que necesita saber que llegó por la marca.
    """
    if meta is None:
        return via_reseller is None
    if meta.get("cause", CAUSA_FALTA_DE_PAGO) != CAUSA_FALTA_DE_PAGO:
        return False
    esperado = str(via_reseller) if via_reseller is not None else None
    return meta.get("via_reseller") == esperado


def reactivar_por_pago(
    db: Session, organization_id: UUID, *, payment_id: Optional[UUID] = None
) -> list[UUID]:
    """
    Levanta lo que un pago de `organization_id` deja sin motivo de suspensión.

    - La cuenta, si está suspendida por falta de pago y no le llegó por su
      marca: la deuda de la marca la paga la marca.
    - Si la cuenta es una marca, las subcuentas que se suspendieron con ella
      (`via_reseller`) por falta de pago.
    - La organización, si se suspendió ella misma por falta de pago.

    No hace commit: va en la transacción del pago. Devuelve los ids de lo que
    reactivó, cuentas y organización.
    """
    from app.models.account import Account, AccountStatus
    from app.models.account_event import ActorType, EventType, TargetType
    from app.models.organization import Organization, OrganizationStatus
    from app.services.audit import AuditService
    from app.utils.datetime import utcnow

    org = db.query(Organization).filter(Organization.id == organization_id).first()
    if org is None:
        return []
    cuenta = db.query(Account).filter(Account.id == org.account_id).first()
    suspendida = AccountStatus.SUSPENDED.value
    reactivadas: list[UUID] = []

    def _registrar(account_id, event_type, target_type, target_id, via=None):
        AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=org.id,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            actor_type=ActorType.SYSTEM.value,
            metadata={
                "anterior": suspendida,
                "nuevo": AccountStatus.ACTIVE.value,
                "reason": "payment",
                "payment_id": str(payment_id) if payment_id else None,
                "via_reseller": str(via) if via is not None else None,
            },
        )

    def _reactivar_cuenta(objetivo, via=None):
        objetivo.status = AccountStatus.ACTIVE.value
        objetivo.updated_at = utcnow()
        _registrar(
            objetivo.id,
            EventType.ACCOUNT_STATUS_CHANGED.value,
            TargetType.ACCOUNT.value,
            objetivo.id,
            via,
        )
        reactivadas.append(objetivo.id)

    evento_cuenta = EventType.ACCOUNT_STATUS_CHANGED.value
    if (
        cuenta is not None
        and _valor(cuenta.status) == suspendida
        and _se_reactiva_al_pagar(_ultima_suspension(db, evento_cuenta, cuenta.id))
    ):
        _reactivar_cuenta(cuenta)
        for hija in descendientes(db, cuenta.id):
            if _valor(hija.status) == suspendida and _se_reactiva_al_pagar(
                _ultima_suspension(db, evento_cuenta, hija.id), via_reseller=cuenta.id
            ):
                _reactivar_cuenta(hija, via=cuenta.id)

    if _valor(
        org.status
    ) == OrganizationStatus.SUSPENDED.value and _se_reactiva_al_pagar(
        _ultima_suspension(db, EventType.ORG_STATUS_CHANGED.value, org.id)
    ):
        org.status = OrganizationStatus.ACTIVE
        _registrar(
            org.account_id,
            EventType.ORG_STATUS_CHANGED.value,
            TargetType.ORGANIZATION.value,
            org.id,
        )
        reactivadas.append(org.id)

    if reactivadas:
        db.flush()
    return reactivadas
