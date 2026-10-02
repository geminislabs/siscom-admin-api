"""
`GET /tenant-config` — qué marca corresponde al Host de la petición.

Es el endpoint que permite que un solo despliegue de Nexus se pinte con la marca
de cada partner (§7). Lo consume el `hooks.server.js` de nexus-web-page en cada
petición, antes de que exista sesión, para que el primer HTML salga ya con el
logo, los colores y el título correctos — y no con los de Geminis durante
200–800 ms, que es lo que se ve hoy y lo que además arruina el unfurl de
WhatsApp, donde el crawler no ejecuta JavaScript.

LA REGLA QUE MÁS ERRORES PREVIENE EN ESTAS PLATAFORMAS
======================================================
**El Host resuelve apariencia y NUNCA autoriza.** El tenant de marca y el tenant
de datos son cosas distintas: la marca la determina el dominio por el que entró
la petición; los datos, el subárbol del usuario autenticado. Que alguien mande
`Host: meromero.com` a mano no le da acceso a nada, porque por aquí no sale un
solo dato de cliente — ni siquiera el `account_id` de la marca.

Confundir ambas resoluciones es el bug clásico de estas arquitecturas, y por eso
este módulo no importa nada de autenticación: no hay dónde equivocarse.
"""

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.tenancy import TenantBranding
from app.schemas.tenant_config import TenantConfigResponse
from app.services.tenancy import normalizar_host, resolver_account_id_de_host

router = APIRouter()

# Lo que se sirve cuando el Host no es de nadie: localhost, la IP del ALB, un
# dominio que aún no se ha verificado, o alguien probando hostnames.
MARCA_POR_DEFECTO = "Nexus"

# El navegador puede cachearlo un rato: cambia cuando el partner publica su
# tema, que es una acción manual y poco frecuente. Corto de todos modos, para
# que publicar se note sin tener que purgar nada.
CACHE_SEGUNDOS = 60


@router.get(
    "/tenant-config",
    response_model=TenantConfigResponse,
    summary="Configuración de marca del Host de la petición",
)
def get_tenant_config(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> TenantConfigResponse:
    """
    Devuelve la marca que corresponde al `Host` de esta petición.

    **Público y sin autenticación**, por diseño: hace falta antes de que exista
    sesión. Devuelve únicamente datos de marca.

    Un Host desconocido **no es un error**: responde 200 con la configuración
    genérica y `is_default: true`. Un 404 obligaría a cada cliente a tratar el
    caso, y el fallo más probable —un dominio recién dado de alta y todavía sin
    verificar— dejaría la aplicación sin pintar en vez de pintarla neutra.
    """
    response.headers["Cache-Control"] = f"public, max-age={CACHE_SEGUNDOS}"
    # El contenido depende del Host: sin esto, una caché intermedia serviría la
    # marca de un partner a otro.
    response.headers["Vary"] = "Host"

    hostname = normalizar_host(request.headers.get("host"))
    if hostname is None:
        return TenantConfigResponse(
            hostname="", brand_name=MARCA_POR_DEFECTO, theme={}, is_default=True
        )

    account_id = resolver_account_id_de_host(hostname, db)

    if account_id is None:
        return TenantConfigResponse(
            hostname=hostname,
            brand_name=MARCA_POR_DEFECTO,
            theme={},
            is_default=True,
        )

    branding = (
        db.query(TenantBranding).filter(TenantBranding.account_id == account_id).first()
    )

    return TenantConfigResponse(
        hostname=hostname,
        brand_name=(
            branding.brand_name
            if branding and branding.brand_name
            else MARCA_POR_DEFECTO
        ),
        # `published`, nunca `draft`: el borrador es lo que el partner está
        # editando y no ha publicado.
        theme=(branding.published if branding else {}) or {},
        is_default=False,
    )
