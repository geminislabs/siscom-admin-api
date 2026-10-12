"""
Endpoints internos para convertir una cuenta en marca (B4, rebanada 4).

La marca la crea Geminis desde GAC (§10, §26): la cuenta sin padre es la marca,
y lo que la habilita son su tipo y sus capabilities comerciales. Hasta ahora
eso solo se podía hacer con un `INSERT` a mano.

Endpoints:
- PATCH  /internal/accounts/{account_id}                      tipo de cuenta
- GET    /internal/accounts/{account_id}/capabilities         propias y efectivas
- PUT    /internal/accounts/{account_id}/capabilities/{code}  fija un techo
- DELETE /internal/accounts/{account_id}/capabilities/{code}  lo quita

QUIÉN
=====
Solo el token PASETO de GAC (`get_auth_solo_servicio`, service="gac",
role="GAC_ADMIN"). Un token de persona de Nexus recibe 403 aunque sea válido:
es el agujero que cerró v1.36.0, y estas son las primeras escrituras del plano
de control sobre cuentas.

QUÉ SE PUEDE ESCRIBIR
=====================
Solo las capabilities **comerciales** (`DEFAULT_ACCOUNT_CAPABILITIES`). Las
operativas —dispositivos, geocercas— son de la organización y tienen sus
propios endpoints; una fila de esas en `account_capabilities` no la leería
nadie.

Una fila no concede más de lo que tiene el ancestro: se puede guardar, pero el
techo descendente la recorta al resolver (`account_capabilities.resolver`). Por
eso las respuestas devuelven el valor propio **y** el efectivo, con quién lo
recortó: GAC tiene que ver que el valor que escribió no es el que rige.

AUDITORÍA
=========
Cada escritura deja un evento en `account_events` de la cuenta afectada, con
`actor_type = service`. El token de GAC lleva el id del usuario de GAC que lo
pidió (`internal_id`); no es un usuario de Nexus, así que va en `metadata` y
no en `actor_user_id`.
"""

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_solo_servicio
from app.db.session import get_db
from app.models.account import Account, AccountStatus, AccountType
from app.models.account_event import ActorType, EventType, TargetType
from app.models.capability import AccountCapability, Capability
from app.schemas.account_tenancy import (
    AccountCapabilityIn,
    AccountCapabilityOut,
    AccountTypeOut,
    AccountTypeUpdate,
)
from app.services import account_capabilities
from app.services.audit import AuditService
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()

get_auth_gac = get_auth_solo_servicio(required_service="gac", required_role="GAC_ADMIN")

# Las capabilities que tienen sentido a nivel cuenta. Es la misma lista que da
# los valores por defecto: una capability comercial sin default no existe.
CODIGOS_COMERCIALES = tuple(account_capabilities.DEFAULT_ACCOUNT_CAPABILITIES)


# =============================================================================
# Helpers
# =============================================================================


def _cuenta_o_404(db: Session, account_id: UUID) -> Account:
    cuenta = db.query(Account).filter(Account.id == account_id).first()
    if cuenta is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Account no encontrado"
        )
    return cuenta


def _capability_comercial_o_404(db: Session, code: str) -> Capability:
    if code not in CODIGOS_COMERCIALES:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                f"'{code}' no es una capability comercial. Las de cuenta son: "
                f"{', '.join(CODIGOS_COMERCIALES)}"
            ),
        )
    capability = db.query(Capability).filter(Capability.code == code).first()
    if capability is None:
        # Sembrada por la 027; si falta, el esquema no es el que espera el código.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"La capability '{code}' no está definida en la base",
        )
    return capability


def _valor_tipado(capability: Capability, valor: Any) -> dict[str, Any]:
    """
    Las tres columnas de valor, con exactamente una llena (el CHECK de la 027).

    El tipo se valida contra `value_type` y no se convierte: un `1` para una
    capability booleana es un error de quien llama, no un `True`. Un `bool` es
    `int` en Python, así que el caso entero lo excluye a propósito.
    """
    tipo = capability.value_type
    if tipo == "bool" and isinstance(valor, bool):
        return {"value_bool": valor, "value_int": None, "value_text": None}
    if tipo == "int" and isinstance(valor, int) and not isinstance(valor, bool):
        if valor < 0:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"'{capability.code}' no admite negativos",
            )
        return {"value_int": valor, "value_bool": None, "value_text": None}
    if tipo == "text" and isinstance(valor, str):
        return {"value_text": valor, "value_bool": None, "value_int": None}
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"'{capability.code}' es de tipo {tipo}; el valor no lo es",
    )


def _salida(
    db: Session, cuenta: Account, capability: Capability
) -> AccountCapabilityOut:
    fila = (
        db.query(AccountCapability)
        .filter(
            AccountCapability.account_id == cuenta.id,
            AccountCapability.capability_id == capability.id,
        )
        .first()
    )
    try:
        resuelta = account_capabilities.resolver(db, cuenta.id, capability.code)
    except account_capabilities.CaminoDeCuentaInvalido:
        # §17: si el árbol no permite decidir, no se inventa un valor.
        logger.error(
            "internal.account_capabilities.sin_camino",
            extra={"account_id": str(cuenta.id)},
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cuenta no tiene un account_path utilizable",
        )
    return AccountCapabilityOut(
        code=capability.code,
        value_type=capability.value_type,
        description=capability.description,
        own_value=fila.get_value() if fila is not None else None,
        reason=fila.reason if fila is not None else None,
        expires_at=fila.expires_at if fila is not None else None,
        expired=fila.is_expired() if fila is not None else False,
        effective_value=resuelta.value,
        source=resuelta.source,
        limited_by=resuelta.limitado_por,
    )


def _auditar(
    db: Session,
    request: Request,
    auth: AuthResult,
    cuenta: Account,
    evento: EventType,
    target_type: TargetType,
    target_id: Optional[UUID],
    metadata: dict[str, Any],
) -> None:
    AuditService.log_event(
        db=db,
        account_id=cuenta.id,
        event_type=evento.value,
        target_type=target_type.value,
        target_id=target_id,
        actor_type=ActorType.SERVICE.value,
        metadata={
            **metadata,
            "service": auth.service,
            "gac_user": auth.payload.get("internal_id"),
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.patch("/{account_id}", response_model=AccountTypeOut)
def cambiar_tipo_de_cuenta(
    account_id: UUID,
    entrada: AccountTypeUpdate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_gac),
):
    """
    Cambia el tipo de la cuenta: RESELLER la convierte en marca, CUSTOMER la
    regresa a cliente final.

    - 409 si la cuenta es PLATFORM: la de Geminis no cambia de papel por API.
    - 409 al regresar a CUSTOMER una cuenta que todavía tiene subcuentas: se
      quedarían colgando de un cliente final.

    Cambiar el tipo no concede nada por sí mismo: la marca propia la habilita
    `white_label_enabled` y la reventa `can_resell`, que se fijan aparte.
    """
    cuenta = _cuenta_o_404(db, account_id)
    anterior = str(getattr(cuenta.account_type, "value", cuenta.account_type))
    nuevo = entrada.account_type

    if anterior == AccountType.PLATFORM.value:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La cuenta de plataforma no cambia de tipo por API",
        )

    if nuevo == anterior:
        return AccountTypeOut(
            id=cuenta.id,
            account_name=cuenta.name,
            account_type=anterior,
            parent_account_id=cuenta.parent_account_id,
            changed=False,
        )

    if nuevo == AccountType.CUSTOMER.value:
        hijas = (
            db.query(Account.id)
            .filter(
                Account.parent_account_id == cuenta.id,
                Account.status != AccountStatus.DELETED.value,
            )
            .count()
        )
        if hijas:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"La cuenta tiene {hijas} subcuenta(s); no puede volver a "
                    "ser cliente final mientras las tenga"
                ),
            )

    cuenta.account_type = nuevo
    cuenta.updated_at = utcnow()
    _auditar(
        db,
        request,
        auth,
        cuenta,
        EventType.ACCOUNT_UPDATED,
        TargetType.ACCOUNT,
        cuenta.id,
        {"campo": "account_type", "anterior": anterior, "nuevo": nuevo},
    )
    db.commit()
    db.refresh(cuenta)

    return AccountTypeOut(
        id=cuenta.id,
        account_name=cuenta.name,
        account_type=nuevo,
        parent_account_id=cuenta.parent_account_id,
        changed=True,
    )


@router.get("/{account_id}/capabilities", response_model=list[AccountCapabilityOut])
def listar_capabilities_de_cuenta(
    account_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_gac),
):
    """
    Las capabilities comerciales de la cuenta: su fila, si la tiene, y el valor
    que rige después del techo de sus ancestros.
    """
    cuenta = _cuenta_o_404(db, account_id)
    capabilities = (
        db.query(Capability)
        .filter(Capability.code.in_(CODIGOS_COMERCIALES))
        .order_by(Capability.code)
        .all()
    )
    return [_salida(db, cuenta, c) for c in capabilities]


@router.put("/{account_id}/capabilities/{code}", response_model=AccountCapabilityOut)
def fijar_capability_de_cuenta(
    account_id: UUID,
    code: str,
    entrada: AccountCapabilityIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_gac),
):
    """
    Crea o reemplaza la fila de la cuenta para esa capability.

    El valor se guarda tal cual, pero rige recortado por los ancestros: la
    respuesta trae `own_value`, `effective_value` y `limited_by`.
    """
    cuenta = _cuenta_o_404(db, account_id)
    capability = _capability_comercial_o_404(db, code)
    columnas = _valor_tipado(capability, entrada.value)

    fila = (
        db.query(AccountCapability)
        .filter(
            AccountCapability.account_id == cuenta.id,
            AccountCapability.capability_id == capability.id,
        )
        .first()
    )
    anterior = fila.get_value() if fila is not None else None
    if fila is None:
        fila = AccountCapability(account_id=cuenta.id, capability_id=capability.id)
        db.add(fila)
    for columna, valor in columnas.items():
        setattr(fila, columna, valor)
    fila.reason = entrada.reason
    fila.expires_at = entrada.expires_at
    fila.updated_at = utcnow()
    db.flush()

    _auditar(
        db,
        request,
        auth,
        cuenta,
        EventType.ACCOUNT_CAPABILITY_SET,
        TargetType.ACCOUNT_CAPABILITY,
        fila.id,
        {
            "code": code,
            "anterior": anterior,
            "nuevo": entrada.value,
            "reason": entrada.reason,
            "expires_at": (
                entrada.expires_at.isoformat() if entrada.expires_at else None
            ),
        },
    )
    db.commit()

    return _salida(db, cuenta, capability)


@router.delete(
    "/{account_id}/capabilities/{code}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def quitar_capability_de_cuenta(
    account_id: UUID,
    code: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_gac),
):
    """
    Borra la fila: la cuenta vuelve a heredar de sus ancestros, o al default si
    nadie en el camino dice nada. No es lo mismo que poner `false` o `0`, que
    sí restringe. Idempotente.
    """
    cuenta = _cuenta_o_404(db, account_id)
    capability = _capability_comercial_o_404(db, code)
    fila = (
        db.query(AccountCapability)
        .filter(
            AccountCapability.account_id == cuenta.id,
            AccountCapability.capability_id == capability.id,
        )
        .first()
    )
    if fila is not None:
        _auditar(
            db,
            request,
            auth,
            cuenta,
            EventType.ACCOUNT_CAPABILITY_REMOVED,
            TargetType.ACCOUNT_CAPABILITY,
            fila.id,
            {"code": code, "anterior": fila.get_value()},
        )
        db.delete(fila)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
