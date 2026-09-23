"""
Endpoints de Gestión de Usuarios de Organizaciones.

Endpoints:
- GET    /organizations/{organization_id}/users
- POST   /organizations/{organization_id}/users
- PATCH  /organizations/{organization_id}/users/{user_id}
- DELETE /organizations/{organization_id}/users/{user_id}

REGLAS DE NEGOCIO:
==================
1. Solo owner puede asignar otro owner
2. Admin NO puede modificar owner
3. No se puede eliminar ni degradar al ÚLTIMO owner de la organización
4. Un usuario solo puede aparecer una vez por organización
5. Roles: owner > admin > billing > member
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_identity_provider, require_organization_role
from app.db.session import get_db
from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.user import User, UserStatus
from app.schemas.organization import (
    AddUserToOrganizationRequest,
    OrganizationUserOut,
    OrganizationUsersListOut,
    UpdateMemberRoleRequest,
)
from app.services.audit import AuditService
from app.services.identity import ErrorDeIdentidad, IdentityProvider
from app.services.organization import OrganizationService

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Helpers de permisos
# =============================================================================


def _verify_org_access(
    db: Session,
    organization_id: UUID,
    auth: AuthResult,
) -> Organization:
    """
    Verifica que el usuario tenga acceso a la organización.

    Returns:
        La organización si tiene acceso

    Raises:
        HTTPException 404 si la organización no existe
        HTTPException 403 si no tiene acceso
    """
    # Obtener la organización actual del usuario
    current_org = (
        db.query(Organization).filter(Organization.id == auth.organization_id).first()
    )
    if not current_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización actual no encontrada",
        )

    # Obtener la organización objetivo
    target_org = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )
    if not target_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    # Verificar que pertenezcan al mismo account
    if target_org.account_id != current_org.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta organización",
        )

    return target_org


def _can_assign_role(
    actor_role: OrganizationRole, target_role: OrganizationRole
) -> bool:
    """
    Verifica si un actor puede asignar un rol específico.

    Reglas:
    - Solo owner puede asignar owner
    - Admin puede asignar admin, billing, member
    - Otros roles no pueden asignar roles
    """
    if actor_role == OrganizationRole.OWNER:
        return True  # Owner puede asignar cualquier rol

    if actor_role == OrganizationRole.ADMIN:
        # Admin puede asignar todo excepto owner
        return target_role != OrganizationRole.OWNER

    return False


def _can_modify_user(
    actor_role: OrganizationRole,
    target_current_role: OrganizationRole,
) -> bool:
    """
    Verifica si un actor puede modificar un usuario con cierto rol.

    Reglas:
    - Owner puede modificar a cualquiera
    - Admin NO puede modificar a owners
    """
    if actor_role == OrganizationRole.OWNER:
        return True

    if actor_role == OrganizationRole.ADMIN:
        return target_current_role != OrganizationRole.OWNER

    return False


def _count_owners(db: Session, organization_id: UUID) -> int:
    """Cuenta el número de owners en una organización."""
    return (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.organization_id == organization_id,
            OrganizationUser.role == OrganizationRole.OWNER.value,
        )
        .count()
    )


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/{organization_id}/users",
    response_model=OrganizationUsersListOut,
)
def list_organization_users(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("member")),
):
    """
    Lista todos los usuarios de una organización.

    Cualquier miembro de la organización puede ver la lista.
    Retorna información básica de cada usuario y su rol.
    """
    # Verificar acceso a la organización
    _verify_org_access(db, organization_id, auth)

    # Obtener miembros
    memberships = (
        db.query(OrganizationUser, User)
        .join(User, OrganizationUser.user_id == User.id)
        .filter(OrganizationUser.organization_id == organization_id)
        .order_by(OrganizationUser.created_at.desc())
        .all()
    )

    users = []
    for membership, user in memberships:
        users.append(
            OrganizationUserOut(
                id=membership.id,
                organization_id=membership.organization_id,
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=(
                    membership.role
                    if isinstance(membership.role, str)
                    else membership.role.value
                ),
                created_at=membership.created_at,
                email_verified=user.email_verified,
            )
        )

    return OrganizationUsersListOut(users=users, total=len(users))


@router.post(
    "/{organization_id}/users",
    response_model=OrganizationUserOut,
    status_code=status.HTTP_201_CREATED,
)
def add_user_to_organization(
    organization_id: UUID,
    data: AddUserToOrganizationRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("admin")),
):
    """
    Agrega un usuario existente a la organización.

    Requiere rol admin o superior.

    Reglas:
    - Solo owner puede agregar otro owner
    - El usuario no debe existir ya en la organización
    - El usuario debe existir en el sistema
    """
    # Verificar acceso a la organización
    org = _verify_org_access(db, organization_id, auth)

    # Obtener el rol del actor
    actor_role = OrganizationService.get_user_role(db, auth.user_id, organization_id)
    if actor_role is None:
        # Verificar si tiene acceso al menos a la org actual
        actor_role = OrganizationService.get_user_role(
            db, auth.user_id, auth.organization_id
        )

    if actor_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para gestionar usuarios",
        )

    # Verificar que puede asignar el rol solicitado
    if not _can_assign_role(actor_role, data.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes permisos para asignar el rol '{data.role.value}'",
        )

    # Verificar que el usuario existe
    target_user = db.query(User).filter(User.id == data.user_id).first()
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado",
        )

    # Verificar que no existe ya en la organización
    existing = (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.organization_id == organization_id,
            OrganizationUser.user_id == data.user_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El usuario ya es miembro de esta organización",
        )

    # Crear la membresía
    membership = OrganizationUser(
        organization_id=organization_id,
        user_id=data.user_id,
        role=data.role,
    )
    db.add(membership)

    # Registrar evento de auditoría
    AuditService.log_org_user_added(
        db=db,
        account_id=org.account_id,
        organization_id=organization_id,
        actor_user_id=auth.user_id,
        target_user_id=data.user_id,
        role=data.role.value,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    db.commit()
    db.refresh(membership)

    logger.info(
        "org_user.added",
        extra={
            "user_id": str(data.user_id),
            "organization_id": str(organization_id),
            "role": data.role.value,
            "actor_user_id": str(auth.user_id),
        },
    )

    return OrganizationUserOut(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=(
            membership.role
            if isinstance(membership.role, str)
            else membership.role.value
        ),
        created_at=membership.created_at,
        email_verified=target_user.email_verified,
    )


@router.patch(
    "/{organization_id}/users/{user_id}",
    response_model=OrganizationUserOut,
)
def update_user_role(
    organization_id: UUID,
    user_id: UUID,
    data: UpdateMemberRoleRequest,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("admin")),
):
    """
    Actualiza el rol de un usuario en la organización.

    Requiere rol admin o superior.

    Reglas:
    - Solo owner puede asignar rol owner
    - Admin NO puede modificar a owners
    - No se puede degradar al último owner
    """
    # Verificar acceso a la organización
    org = _verify_org_access(db, organization_id, auth)

    # Obtener el rol del actor
    actor_role = OrganizationService.get_user_role(db, auth.user_id, organization_id)
    if actor_role is None:
        actor_role = OrganizationService.get_user_role(
            db, auth.user_id, auth.organization_id
        )

    if actor_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para gestionar usuarios",
        )

    # Obtener la membresía actual
    membership = (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.organization_id == organization_id,
            OrganizationUser.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la organización",
        )

    # Obtener el rol actual del usuario target
    current_role_str = (
        membership.role if isinstance(membership.role, str) else membership.role.value
    )
    current_role = OrganizationRole(current_role_str)

    # Verificar que puede modificar a este usuario
    if not _can_modify_user(actor_role, current_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para modificar a este usuario",
        )

    # Verificar que puede asignar el nuevo rol
    if not _can_assign_role(actor_role, data.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"No tienes permisos para asignar el rol '{data.role.value}'",
        )

    # Verificar que no se degrada al último owner
    if current_role == OrganizationRole.OWNER and data.role != OrganizationRole.OWNER:
        owner_count = _count_owners(db, organization_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede degradar al último owner de la organización",
            )

    # Obtener datos del usuario para la respuesta
    target_user = db.query(User).filter(User.id == user_id).first()

    old_role = current_role_str

    # Actualizar el rol
    membership.role = data.role

    # Registrar evento de auditoría
    AuditService.log_org_user_role_changed(
        db=db,
        account_id=org.account_id,
        organization_id=organization_id,
        actor_user_id=auth.user_id,
        target_user_id=user_id,
        old_role=old_role,
        new_role=data.role.value,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    db.commit()
    db.refresh(membership)

    logger.info(
        "org_user.role_changed",
        extra={
            "user_id": str(user_id),
            "organization_id": str(organization_id),
            "old_role": old_role,
            "new_role": data.role.value,
            "actor_user_id": str(auth.user_id),
        },
    )

    return OrganizationUserOut(
        id=membership.id,
        organization_id=membership.organization_id,
        user_id=target_user.id,
        email=target_user.email,
        full_name=target_user.full_name,
        role=(
            membership.role
            if isinstance(membership.role, str)
            else membership.role.value
        ),
        created_at=membership.created_at,
        email_verified=target_user.email_verified,
    )


@router.delete(
    "/{organization_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_user_from_organization(
    organization_id: UUID,
    user_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("admin")),
    idp: IdentityProvider = Depends(get_identity_provider),
):
    """
    Elimina un usuario de la organización.

    Requiere rol admin o superior.

    Reglas:
    - Admin NO puede eliminar a owners
    - No se puede eliminar al último owner
    - Un usuario no puede eliminarse a sí mismo (debe transferir ownership primero)

    **Además de borrar la membresía, marca la fila `INACTIVE`.** Hasta la 029
    esto sólo borraba la membresía y dejaba la fila de `users` intacta, con su
    correo y su credencial — lo que producía un callejón sin salida: al volver
    a invitar a esa persona, `invite_user` encontraba la fila y respondía 400,
    y no había ningún endpoint que la borrara. La fila **no se borra** (veinte
    FK la referencian, varias en cascada); se desactiva.
    """
    # Verificar acceso a la organización
    org = _verify_org_access(db, organization_id, auth)

    # Obtener el rol del actor
    actor_role = OrganizationService.get_user_role(db, auth.user_id, organization_id)
    if actor_role is None:
        actor_role = OrganizationService.get_user_role(
            db, auth.user_id, auth.organization_id
        )

    if actor_role is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para gestionar usuarios",
        )

    # Obtener la membresía
    membership = (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.organization_id == organization_id,
            OrganizationUser.user_id == user_id,
        )
        .first()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado en la organización",
        )

    # Obtener el rol actual del usuario target
    current_role_str = (
        membership.role if isinstance(membership.role, str) else membership.role.value
    )
    current_role = OrganizationRole(current_role_str)

    # Verificar que puede modificar a este usuario
    if not _can_modify_user(actor_role, current_role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para eliminar a este usuario",
        )

    # Verificar que no se elimina al último owner
    if current_role == OrganizationRole.OWNER:
        owner_count = _count_owners(db, organization_id)
        if owner_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede eliminar al último owner de la organización",
            )

    # Registrar evento de auditoría ANTES de eliminar
    AuditService.log_org_user_removed(
        db=db,
        account_id=org.account_id,
        organization_id=organization_id,
        actor_user_id=auth.user_id,
        target_user_id=user_id,
        previous_role=current_role_str,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # Eliminar la membresía
    db.delete(membership)

    # Y desactivar la fila, que es lo que rompe el callejón sin salida.
    #
    # Sólo cuando la organización de la que se le saca es **la suya**. Alguien
    # puede ser miembro de varias: quitarle una membresía ajena no lo da de
    # baja del sistema.
    target = db.query(User).filter(User.id == user_id).first()
    desactivado = False
    if target is not None and target.organization_id == organization_id:
        target.status = UserStatus.INACTIVE.value
        db.add(target)
        desactivado = True

    db.commit()

    # El refuerzo en el proveedor va **después** del commit, y su fallo no
    # tumba la operación: la fuente de verdad es `users.status`, ya escrito
    # (§9, regla 1). Si esto falla, queda una credencial habilitada que no
    # autoriza nada, porque `deps.py` revalida contra Postgres en cada
    # petición. Al revés —deshabilitar en Cognito y que el commit fallara—
    # dejaría a alguien sin poder entrar y activo en la base, que es peor.
    if desactivado and target is not None:
        try:
            idp.deshabilitar(handle=target.external_id)
        except ErrorDeIdentidad as e:
            logger.error(
                "org_user.disable_failed",
                extra={"user_id": str(user_id), "error_code": e.codigo},
            )

    logger.info(
        "org_user.removed",
        extra={
            "user_id": str(user_id),
            "organization_id": str(organization_id),
            "previous_role": current_role_str,
            "actor_user_id": str(auth.user_id),
            "deactivated": desactivado,
        },
    )

    return None
