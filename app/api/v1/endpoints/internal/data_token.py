"""
`POST /api/v1/internal/data-token`: el data token del mapa de dispositivos de GAC.

GAC lee comunicaciones de siscom-api por un proxy de gac-web. Mientras siscom-api
no exija el data token (`DATA_TOKEN_ENFORCED=false`) eso funciona sin
credencial; en cuanto lo exija, GAC necesita uno como cualquier otro cliente.
Éste se limita a los dispositivos que pide, con la misma vida que el de una
sesión de Nexus, y deja rastro (`jti`) para cruzarlo con los logs de siscom-api.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthResult,
    get_auth_for_gac_admin,
    get_data_token_issuer,
    get_request_locale,
    get_scope_store,
)
from app.core.i18n import t
from app.db.session import get_db
from app.models.device import Device
from app.schemas.internal_data_token import (
    GacDataTokenDevice,
    GacDataTokenIn,
    GacDataTokenOut,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "",
    response_model=GacDataTokenOut,
    status_code=status.HTTP_200_OK,
    responses={404: {"description": "Algún IMEI no existe; `missing` lista cuáles"}},
)
def issue_gac_data_token(
    body: GacDataTokenIn,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
    issuer=Depends(get_data_token_issuer),
    store=Depends(get_scope_store),
    locale: str = Depends(get_request_locale),
):
    """
    Emite un data token para leer de siscom-api los dispositivos pedidos.

    Devuelve, junto al token, el `device_ref` de cada IMEI: es lo que hay que
    poner en las rutas y en el WebSocket de siscom-api.

    - 404 si algún IMEI no existe (`missing` dice cuáles). No se emite a medias:
      un token sin uno de los dispositivos daría 403 en una pantalla que no sabe
      por qué.
    - 503 si falta la clave de firma, Valkey o el secreto del índice.
    """
    from app.services.data_token_issuance import issue_gac_token
    from app.services.scope_store import (
        RevocationIndexNotConfigured,
        ScopeStoreUnavailable,
    )
    from app.utils.data_token import DataTokenKeyNotConfigured

    filas = (
        db.query(Device.device_id, Device.device_ref)
        .filter(Device.device_id.in_(body.device_ids))
        .all()
    )
    ref_por_imei = dict(filas)
    faltan = [imei for imei in body.device_ids if imei not in ref_por_imei]
    if faltan:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content={"detail": "Dispositivos no encontrados", "missing": faltan},
        )

    operador = str((auth.payload or {}).get("internal_id") or "desconocido")
    try:
        issued = issue_gac_token(
            devices=[(ref_por_imei[imei], imei) for imei in body.device_ids],
            operator=operador,
            issuer=issuer,
            store=store,
        )
    except (
        DataTokenKeyNotConfigured,
        ScopeStoreUnavailable,
        RevocationIndexNotConfigured,
    ) as exc:
        logger.error(
            "internal.data_token.unavailable",
            extra={
                "extra_data": {
                    "gac_user": operador,
                    "error_type": type(exc).__name__,
                }
            },
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=t("auth.data_service_unavailable", locale),
        ) from exc

    logger.info(
        "internal.data_token.emitido",
        extra={
            "extra_data": {
                "gac_user": operador,
                "jti": str(issued.jti),
                "devices": len(body.device_ids),
            }
        },
    )

    return GacDataTokenOut(
        token=issued.token,
        expires_at=issued.expires_at,
        expires_in=int((issued.expires_at - issued.issued_at).total_seconds()),
        devices=[
            GacDataTokenDevice(device_id=imei, device_ref=ref_por_imei[imei])
            for imei in body.device_ids
        ],
    )
