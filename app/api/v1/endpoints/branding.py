"""
Endpoints de la pantalla de marca (B4, función 6 de §10).

Endpoints:
- GET    /accounts/{account_id}/branding           borrador y publicado
- PUT    /accounts/{account_id}/branding/draft     valida, deriva tokens, guarda
- POST   /accounts/{account_id}/branding/publish   el borrador pasa a publicado
- DELETE /accounts/{account_id}/branding/draft     descarta el borrador

QUIÉN PUEDE
===========
Dos condiciones, y las dos en cada endpoint (también en el GET: el borrador no
es público):

  1. El permiso `branding.write` en esa cuenta (`require_account_permission`):
     hoy lo tienen su owner y su admin. Se compara contra la membresía real en
     `account_users`, nunca contra el `Host`, que solo elige apariencia (§3).
  2. La capability `white_label_enabled` resuelta con el techo descendente: una
     cuenta no puede tener marca propia si un ancestro no la tiene (D3).

BORRADOR Y PUBLICADO
====================
Guardar nunca cambia lo que ven los usuarios: solo `publish` lo hace. Eso
incluye el nombre de la marca. `brand_name` es columna —la leen `/tenant-config`
y los correos—, así que el borrador lo lleva dentro del jsonb y `publish` lo
copia a la columna. Si el `PUT` escribiera la columna, el nombre cambiaría en
vivo sin publicar.

El borrador guardado siempre pasa AA: el servidor deriva los tokens al guardar y
responde 422 si algún par no cumple. `publish` vuelve a derivar desde las
semillas, así que lo publicado cumple aunque el algoritmo haya cambiado entre
guardar y publicar.

Cada `publish` deja en `account_events` el publicado anterior: volver atrás es
publicar lo que había, sin tabla de versiones. `/tenant-config` cachea 60 s.
"""

import logging
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, require_account_permission
from app.db.session import get_db
from app.models.account_event import EventType, TargetType
from app.models.tenancy import TenantBranding
from app.schemas.branding import (
    VERSION_DEL_CONTRATO,
    BrandingDraftIn,
    BrandingDraftOut,
    BrandingOut,
)
from app.services import account_capabilities, marca_tema
from app.services.audit import AuditService
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================


def _editor_de_marca(
    account_id: UUID,
    auth: AuthResult = Depends(require_account_permission("branding.write")),
    db: Session = Depends(get_db),
) -> AuthResult:
    """El permiso y la capability. Ver «Quién puede» en la cabecera."""
    try:
        habilitada = account_capabilities.puede(db, account_id, "white_label_enabled")
    except account_capabilities.CaminoDeCuentaInvalido:
        # §17: si el árbol no permite decidir, no se concede.
        logger.error(
            "branding.capability_sin_camino", extra={"account_id": str(account_id)}
        )
        habilitada = False

    if not habilitada:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="La cuenta no tiene habilitada la marca propia",
        )
    return auth


def _fila(db: Session, account_id: UUID) -> Optional[TenantBranding]:
    return (
        db.query(TenantBranding).filter(TenantBranding.account_id == account_id).first()
    )


def _como_salida(account_id: UUID, fila: Optional[TenantBranding]) -> dict[str, Any]:
    if fila is None:
        return {"account_id": account_id}
    return {
        "account_id": account_id,
        "brand_name": fila.brand_name,
        "draft": fila.draft,
        "published": fila.published or {},
        "published_at": fila.published_at,
        "published_by": fila.published_by,
    }


def _tema_o_422(entrada: BrandingDraftIn) -> tuple[dict[str, Any], marca_tema.Tema]:
    """El jsonb del borrador con sus tokens, o 422 con los pares que fallan."""
    tema = marca_tema.derivar(entrada.seed.primary, entrada.seed.accent)
    if tema.fallos:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "contraste_insuficiente",
                "message": "Algún par de colores no alcanza el contraste WCAG AA",
                "pairs": [p.como_dict() for p in tema.fallos],
            },
        )
    contenido = entrada.model_dump(exclude_none=True)
    contenido["version"] = VERSION_DEL_CONTRATO
    contenido["tokens"] = tema.tokens
    return contenido, tema


def _auditar(
    db: Session,
    request: Request,
    auth: AuthResult,
    account_id: UUID,
    evento: EventType,
    metadata: Optional[dict] = None,
) -> None:
    AuditService.log_event(
        db=db,
        account_id=account_id,
        actor_user_id=auth.user_id,
        event_type=evento.value,
        target_type=TargetType.TENANT_BRANDING.value,
        target_id=account_id,
        metadata=metadata,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get("/{account_id}/branding", response_model=BrandingOut)
def obtener_marca(
    account_id: UUID,
    auth: AuthResult = Depends(_editor_de_marca),
    db: Session = Depends(get_db),
):
    """El borrador y lo publicado. Sin fila todavía, todo vacío: no es un 404."""
    return _como_salida(account_id, _fila(db, account_id))


@router.put("/{account_id}/branding/draft", response_model=BrandingDraftOut)
def guardar_borrador(
    account_id: UUID,
    entrada: BrandingDraftIn,
    request: Request,
    auth: AuthResult = Depends(_editor_de_marca),
    db: Session = Depends(get_db),
):
    """
    Valida, deriva los tokens y guarda el borrador. No cambia lo publicado.

    422 si un campo no es válido o si algún par no alcanza AA; en ese caso
    `detail.pairs` dice cuál y con qué ratio.
    """
    contenido, tema = _tema_o_422(entrada)

    fila = _fila(db, account_id)
    if fila is None:
        fila = TenantBranding(account_id=account_id)
        db.add(fila)
    fila.draft = contenido
    fila.updated_at = utcnow()

    _auditar(db, request, auth, account_id, EventType.BRANDING_DRAFT_SAVED)
    db.commit()
    db.refresh(fila)

    return {
        **_como_salida(account_id, fila),
        "contrast": [p.como_dict() for p in tema.pares],
        "adjustments": tema.ajustes,
    }


@router.post("/{account_id}/branding/publish", response_model=BrandingOut)
def publicar(
    account_id: UUID,
    request: Request,
    auth: AuthResult = Depends(_editor_de_marca),
    db: Session = Depends(get_db),
):
    """
    El borrador pasa a publicado y deja de existir. 409 si no hay borrador.

    Es lo único que cambia lo que ven los usuarios: `/tenant-config`, los
    correos y, cuando llegue el resto de la Fase 4, la aplicación.
    """
    fila = _fila(db, account_id)
    if fila is None or not fila.draft:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No hay borrador que publicar",
        )

    # Se vuelve a validar y derivar: lo publicado cumple aunque el contrato o
    # el algoritmo hayan cambiado desde que se guardó el borrador.
    contenido, _ = _tema_o_422(BrandingDraftIn.model_validate(fila.draft))
    brand_name = contenido.pop("brand_name")

    anterior = {"brand_name": fila.brand_name, "published": fila.published or {}}

    fila.brand_name = brand_name
    fila.published = contenido
    fila.draft = None
    fila.published_at = utcnow()
    fila.published_by = auth.user_id
    fila.updated_at = fila.published_at

    _auditar(
        db,
        request,
        auth,
        account_id,
        EventType.BRANDING_PUBLISHED,
        metadata={"anterior": anterior},
    )
    db.commit()
    db.refresh(fila)

    return _como_salida(account_id, fila)


@router.delete(
    "/{account_id}/branding/draft",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def descartar_borrador(
    account_id: UUID,
    request: Request,
    auth: AuthResult = Depends(_editor_de_marca),
    db: Session = Depends(get_db),
):
    """Borra el borrador; lo publicado queda intacto. Idempotente."""
    fila = _fila(db, account_id)
    if fila is not None and fila.draft is not None:
        fila.draft = None
        fila.updated_at = utcnow()
        _auditar(db, request, auth, account_id, EventType.BRANDING_DRAFT_DISCARDED)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
