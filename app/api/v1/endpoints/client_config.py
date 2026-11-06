"""
`GET /api/v1/client-config`: la app pregunta al arrancar si su versión vale.

**Público y sin autenticación**, por diseño: la app tiene que poder preguntarlo
antes de iniciar sesión, y una versión que ya no sabe autenticarse es justo la
que más necesita la respuesta. Tampoco depende de la marca: la versión mínima es
de la app, no del partner. Sólo devuelve la política, que no es secreta.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.client_version_policy import ClientVersionPolicy
from app.schemas.client_config import ClientConfigResponse
from app.services.client_version_policy import PLATAFORMAS, Actualizacion, evaluar

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get(
    "/client-config",
    response_model=ClientConfigResponse,
    summary="Política de versiones para una app móvil",
)
def get_client_config(
    platform: Optional[str] = Query(None, description="`ios` o `android`"),
    version: Optional[str] = Query(None, max_length=64, description="Ej. `1.2.0`"),
    build: Optional[str] = Query(None, max_length=64, description="Número de build"),
    db: Session = Depends(get_db),
) -> ClientConfigResponse:
    """
    `update`:
    - `required`: la versión está por debajo del mínimo o en la lista negra.
      La app debe bloquearse y mandar a `store_url`.
    - `optional`: hay una versión más nueva (`latest_version`). Avisar.
    - `none`: nada que hacer. También cuando la versión no se puede leer:
      no se bloquea a nadie por un error de parseo.

    400 si falta `platform` o no es `ios`/`android`.
    """
    plataforma = (platform or "").strip().lower()
    if plataforma not in PLATAFORMAS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="platform debe ser 'ios' o 'android'",
        )

    politica = db.get(ClientVersionPolicy, plataforma)
    if politica is None:
        # La migración siembra las dos; si falta una, sin política no se bloquea.
        logger.warning(
            "client_config.sin_politica", extra={"extra_data": {"platform": plataforma}}
        )
        return ClientConfigResponse(update=Actualizacion.NONE.value)

    actualizacion = evaluar(
        version,
        min_supported_version=politica.min_supported_version,
        latest_version=politica.latest_version,
        blocked_versions=politica.blocked_versions,
    )
    logger.info(
        "client_config.consultado",
        extra={
            "extra_data": {
                "client_platform": plataforma,
                "client_version": version,
                "client_build": build,
                "update": actualizacion.value,
            }
        },
    )
    return ClientConfigResponse(
        update=actualizacion.value,
        latest_version=politica.latest_version,
        min_supported_version=politica.min_supported_version,
        store_url=politica.store_url,
    )
