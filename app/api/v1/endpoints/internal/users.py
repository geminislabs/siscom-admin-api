"""Superficie interna de usuarios — la que usa GAC.

POR QUE EXISTE, Y POR QUE NO BASTA LA DE NEXUS
==============================================
La `v1.34.0` dejó a Nexus dar de baja a alguien: `DELETE
/organizations/{org}/users/{id}` borra la membresía y marca la fila INACTIVE.
Eso cubre el caso normal —un admin saca a alguien de **su** organización— y no
cubre el que motivó todo esto.

**Los siete huérfanos no se pueden tocar por esa puerta.** Su
`organization_id` apunta a una organización que **no existe** (`users.organization_id`
no tiene clave foránea en producción), así que `_verify_org_access` falla antes
de llegar al usuario. El endpoint que existe justo para desactivar gente no
puede desactivarlos.

Por eso esta superficie **direcciona al usuario por su id y no pasa por
organización ninguna**. Es la diferencia de fondo con la de Nexus, no un atajo:
el plano de control tiene que poder arreglar precisamente los estados que el
plano de la aplicación no sabe representar.

LO QUE ESTO NO HACE
===================
No borra usuarios, y no va a hacerlo. Veinte claves foráneas referencian
`users`, varias con ON DELETE CASCADE hacia `mobility.devices`,
`team.members`, `user_units` y `user_devices`: borrar a alguien se llevaría por
delante datos que no son suyos. Dar de baja es poner `INACTIVE`.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import and_, exists, not_
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthResult,
    get_auth_solo_servicio,
    get_identity_provider,
)
from app.db.session import get_db
from app.models.organization import Organization
from app.models.user import User, UserStatus
from app.schemas.internal_user import (
    InternalUserOut,
    InternalUserStatusIn,
    InternalUserStatusOut,
)
from app.services.identity import ErrorDeIdentidad, IdentityProvider

logger = logging.getLogger(__name__)

router = APIRouter()

get_auth_for_internal_users = get_auth_solo_servicio(
    required_service="gac",
    required_role="GAC_ADMIN",
)


def _es_huerfano():
    """Predicado de «su organización no existe», reutilizable en filtro y salida.

    Es la misma consulta del contador (4) del runbook de la 029, promovida de
    SQL suelto a algo que el código puede ejercer. Mientras no exista la clave
    foránea de `users.organization_id`, este predicado es la única forma de
    saberlo.
    """
    return and_(
        User.organization_id.isnot(None),
        not_(exists().where(Organization.id == User.organization_id)),
    )


@router.get("", response_model=list[InternalUserOut])
def list_internal_users(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_users),
    status_filter: Optional[UserStatus] = Query(
        None, alias="status", description="Filtrar por estado (ACTIVE / INACTIVE)"
    ),
    organization_id: Optional[UUID] = Query(
        None, description="Filtrar por organización"
    ),
    search: Optional[str] = Query(
        None, description="Buscar por correo (parcial, case-insensitive)"
    ),
    solo_huerfanos: bool = Query(
        False,
        alias="orphaned",
        description="Sólo usuarios cuya organización no existe",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Lista usuarios del sistema entero, sin pasar por organización.

    `orphaned=true` es el que justifica el endpoint: devuelve exactamente los
    usuarios que la vía de Nexus no puede alcanzar.
    """
    query = db.query(User)

    if status_filter is not None:
        query = query.filter(User.status == status_filter.value)
    if organization_id is not None:
        query = query.filter(User.organization_id == organization_id)
    if search:
        query = query.filter(User.email.ilike(f"%{search}%"))
    if solo_huerfanos:
        query = query.filter(_es_huerfano())

    usuarios = query.order_by(User.email).limit(limit).offset(offset).all()

    # Una sola consulta para saber qué organizaciones existen, en vez de una por
    # usuario. Con `limit` a 200 la diferencia no es dramática, pero el patrón
    # N+1 dentro de un plano de control es el que acaba doliendo cuando alguien
    # lo llama en bucle.
    ids_org = {u.organization_id for u in usuarios if u.organization_id}
    existentes = set()
    if ids_org:
        existentes = {
            fila[0]
            for fila in db.query(Organization.id)
            .filter(Organization.id.in_(ids_org))
            .all()
        }

    return [
        InternalUserOut(
            id=u.id,
            email=u.email,
            full_name=u.full_name,
            status=u.status,
            organization_id=u.organization_id,
            huerfano=bool(u.organization_id) and u.organization_id not in existentes,
            is_master=bool(u.is_master),
            email_verified=bool(u.email_verified),
            created_at=u.created_at,
        )
        for u in usuarios
    ]


@router.patch("/{user_id}/status", response_model=InternalUserStatusOut)
def set_internal_user_status(
    user_id: UUID,
    data: InternalUserStatusIn,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_users),
    idp: IdentityProvider = Depends(get_identity_provider),
):
    """Activa o desactiva a un usuario, exista o no su organización.

    **No verifica la organización a propósito.** Ese es el punto: los usuarios
    que hay que arreglar son los que tienen una organización que no existe.

    Idempotente: poner el estado que ya tiene no es un error ni vuelve a llamar
    al proveedor.
    """
    usuario = db.query(User).filter(User.id == user_id).first()
    if usuario is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    nuevo = data.status.value
    if usuario.status == nuevo:
        # Sin cambio no se toca el proveedor: `deshabilitar` y `habilitar` son
        # idempotentes, pero llamarlas de más convierte cada refresco de una
        # pantalla en tráfico contra Cognito.
        return InternalUserStatusOut(
            id=usuario.id,
            email=usuario.email,
            status=usuario.status,
            proveedor_sincronizado=True,
            detalle="Sin cambio: ya estaba en ese estado",
        )

    anterior = usuario.status
    usuario.status = nuevo
    db.add(usuario)
    db.commit()
    db.refresh(usuario)

    # El refuerzo va **después** del commit y su fallo no revierte nada: la
    # fuente de verdad es `users.status`, ya escrito (§9, regla 1). Si esto
    # falla queda una credencial habilitada que no autoriza nada, porque
    # `deps.py` revalida contra Postgres en cada petición. Al revés —tocar
    # Cognito primero y que el commit fallara— dejaría a alguien sin poder
    # entrar y activo en la base, que es peor.
    sincronizado = True
    detalle = None
    try:
        if nuevo == UserStatus.INACTIVE.value:
            idp.deshabilitar(handle=usuario.external_id)
        else:
            idp.habilitar(handle=usuario.external_id)
    except ErrorDeIdentidad as e:
        sincronizado = False
        detalle = f"La fila quedó en {nuevo}, pero el proveedor no se pudo actualizar [{e.codigo}]: {e.mensaje}"
        logger.error(f"[INTERNAL USER STATUS] user={user_id} {detalle}")

    logger.info(
        f"[INTERNAL USER STATUS] user={user_id} {anterior} -> {nuevo} "
        f"por actor={auth.user_id or 'servicio'} "
        f"motivo={data.motivo or '(sin motivo)'} "
        f"proveedor_sincronizado={sincronizado} "
        f"ip={request.client.host if request.client else None}"
    )

    return InternalUserStatusOut(
        id=usuario.id,
        email=usuario.email,
        status=usuario.status,
        proveedor_sincronizado=sincronizado,
        detalle=detalle,
    )
