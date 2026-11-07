"""
`/api/v1/client-version-policy`: GAC administra la política de versiones (§3.3).

Sustituye al runbook `docs/runbooks/politica-de-versiones.md`, que la cambiaba
por SQL. Sólo GAC (`get_auth_for_gac_admin`): la política decide qué
instalaciones se quedan sin app.

Los 422 tienen siempre la forma `{"detail": "...", "field": "..."}`, también
los de validación de FastAPI, para que GAC muestre el error junto al campo.
`field` es `null` cuando el error no es de un campo concreto.

Un cambio llega a `client-config` al instante y al middleware 426 en hasta
`CACHE_SEGUNDOS` (cada worker tiene su caché; la de éste se vacía al guardar).
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, List

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.client_version_gate import invalidar_cache
from app.api.deps import AuthResult, get_auth_for_gac_admin
from app.db.session import get_db
from app.models.client_version_policy import ClientVersionPolicy
from app.models.mobility_device import MobilityDevice
from app.schemas.client_version_policy import (
    ClientVersionPolicyIn,
    ClientVersionPolicyOut,
    InstallsOut,
    InstallsVersion,
    PreviewOut,
    PreviewVersion,
)
from app.services.client_version_policy import (
    PLATAFORMAS,
    Actualizacion,
    PoliticaInvalida,
    evaluar,
    validar_politica,
)

logger = logging.getLogger(__name__)

DESCONOCIDA = "desconocida"


def _error_422(detalle: str, campo) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"detail": detalle, "field": campo},
    )


class _RutaConCampo(APIRoute):
    """Da a los errores de validación de FastAPI la forma `{detail, field}`."""

    def get_route_handler(self) -> Callable:
        original = super().get_route_handler()

        async def handler(request: Request):
            try:
                return await original(request)
            except RequestValidationError as exc:
                primero = (exc.errors() or [{}])[0]
                loc = primero.get("loc") or ()
                campo = str(loc[1]) if len(loc) > 1 else None
                return _error_422(primero.get("msg", "Petición inválida"), campo)

        return handler


router = APIRouter(route_class=_RutaConCampo)


def _plataforma(platform: str) -> str:
    plataforma = platform.strip().lower()
    if plataforma not in PLATAFORMAS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Plataforma desconocida: debe ser 'ios' o 'android'",
        )
    return plataforma


def _instalaciones(db: Session, plataforma: str, dias: int) -> List[InstallsVersion]:
    """Instalaciones vistas en los últimos `dias`, por versión de la app.

    Cuenta filas de `mobility.devices` por `last_seen_at`, no por `is_active`:
    cerrar sesión desactiva el push, pero la app sigue instalada. `platform`
    la escribe cada cliente, de ahí el `lower`.
    """
    desde = datetime.now(timezone.utc) - timedelta(days=dias)
    filas = (
        db.query(MobilityDevice.app_version, func.count())
        .filter(
            func.lower(MobilityDevice.platform) == plataforma,
            MobilityDevice.last_seen_at >= desde,
        )
        .group_by(MobilityDevice.app_version)
        .all()
    )
    conteo: dict = {}
    for version, cantidad in filas:
        clave = (version or "").strip() or DESCONOCIDA
        conteo[clave] = conteo.get(clave, 0) + cantidad
    return [
        InstallsVersion(app_version=version, installs=cantidad)
        for version, cantidad in sorted(
            conteo.items(), key=lambda par: (-par[1], par[0])
        )
    ]


@router.get("", response_model=List[ClientVersionPolicyOut])
def list_policies(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
) -> List[ClientVersionPolicy]:
    """Las dos filas (`android`, `ios`)."""
    return db.query(ClientVersionPolicy).order_by(ClientVersionPolicy.platform).all()


@router.put("/{platform}", response_model=ClientVersionPolicyOut)
def update_policy(
    platform: str,
    cuerpo: ClientVersionPolicyIn,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
):
    """Reemplaza la fila entera. 404 si la plataforma no existe, 422 `{detail, field}`."""
    plataforma = _plataforma(platform)
    try:
        nueva = validar_politica(plataforma, **cuerpo.model_dump())
    except PoliticaInvalida as exc:
        return _error_422(exc.detalle, exc.campo)

    fila = db.get(ClientVersionPolicy, plataforma)
    if fila is None:
        # La 047 siembra las dos; si alguien borró una, guardar la recrea.
        fila = ClientVersionPolicy(platform=plataforma)
        db.add(fila)
        antes = None
    else:
        antes = {campo: getattr(fila, campo) for campo in nueva}
        antes["blocked_versions"] = list(fila.blocked_versions or ())

    autor = (auth.payload or {}).get("internal_id")
    for campo, valor in nueva.items():
        setattr(fila, campo, valor)
    fila.updated_at = func.now()
    fila.updated_by = f"gac:{autor}" if autor else "gac"
    db.commit()
    db.refresh(fila)
    invalidar_cache()

    logger.info(
        "client_version_policy.actualizada",
        extra={
            "extra_data": {
                "platform": plataforma,
                "updated_by": fila.updated_by,
                "antes": antes,
                "despues": nueva,
            }
        },
    )
    return fila


@router.get("/{platform}/installs", response_model=InstallsOut)
def get_installs(
    platform: str,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
) -> InstallsOut:
    """Instalaciones activas por versión. Sólo conteos: nada de usuarios ni equipos."""
    plataforma = _plataforma(platform)
    versiones = _instalaciones(db, plataforma, days)
    return InstallsOut(
        platform=plataforma,
        days=days,
        total=sum(v.installs for v in versiones),
        versions=versiones,
    )


@router.post("/{platform}/preview", response_model=PreviewOut)
def preview_policy(
    platform: str,
    cuerpo: ClientVersionPolicyIn,
    days: int = Query(30, ge=1, le=365),
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
):
    """Qué pasaría con las instalaciones activas. **No guarda nada.**

    Clasifica con la misma `evaluar` que `client-config` y el 426, así que
    una versión ilegible o `desconocida` sale `none`, como en la app.
    """
    plataforma = _plataforma(platform)
    try:
        nueva = validar_politica(plataforma, **cuerpo.model_dump())
    except PoliticaInvalida as exc:
        return _error_422(exc.detalle, exc.campo)

    versiones = []
    requeridas = opcionales = 0
    for item in _instalaciones(db, plataforma, days):
        actualizacion = evaluar(
            None if item.app_version == DESCONOCIDA else item.app_version,
            min_supported_version=nueva["min_supported_version"],
            latest_version=nueva["latest_version"],
            blocked_versions=nueva["blocked_versions"],
        )
        if actualizacion is Actualizacion.REQUIRED:
            requeridas += item.installs
        elif actualizacion is Actualizacion.OPTIONAL:
            opcionales += item.installs
        versiones.append(
            PreviewVersion(
                app_version=item.app_version,
                installs=item.installs,
                update=actualizacion.value,
            )
        )
    return PreviewOut(
        platform=plataforma,
        days=days,
        total=sum(v.installs for v in versiones),
        required=requeridas,
        optional=opcionales,
        versions=versiones,
    )
