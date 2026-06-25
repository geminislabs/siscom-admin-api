"""
Endpoints de Gestión de Organizations.

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación)
Organization = Raíz operativa (permisos, uso diario)

Un Account puede tener múltiples Organizations.

ENDPOINTS:
==========
- POST /organizations: Crear nueva organización dentro del Account del usuario
- GET /organizations: Listar organizaciones del Account del usuario
- GET /organizations/{id}: Obtener organización por ID
- PATCH /organizations/{id}: Actualizar organización
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, require_organization_role
from app.db.session import get_db
from app.models.organization import Organization, OrganizationStatus
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization(
    data: OrganizationCreate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("owner")),
):
    """
    Crea una nueva organización dentro del Account del usuario.

    Solo usuarios con rol 'owner' pueden crear organizaciones.

    La nueva organización:
    - Pertenece al mismo Account del usuario
    - Se crea en estado ACTIVE
    - El usuario que la crea se añade como OWNER

    Args:
        data: Datos de la organización a crear

    Returns:
        OrganizationOut con la información de la organización creada
    """
    # Obtener el account_id del usuario actual
    current_org = (
        db.query(Organization).filter(Organization.id == auth.organization_id).first()
    )

    if not current_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización actual no encontrada",
        )

    account_id = current_org.account_id

    # Crear la nueva organización
    new_org = Organization(
        account_id=account_id,
        name=data.name,
        billing_email=data.billing_email,
        country=data.country or "MX",
        timezone=data.timezone or "America/Mexico_City",
        status=OrganizationStatus.ACTIVE,
    )
    db.add(new_org)
    db.flush()

    # Añadir al usuario como OWNER de la nueva organización
    membership = OrganizationUser(
        organization_id=new_org.id,
        user_id=auth.user_id,
        role=OrganizationRole.OWNER,
    )
    db.add(membership)

    db.commit()
    db.refresh(new_org)

    logger.info(
        f"[ORGANIZATION CREATE] Nueva organización '{data.name}' creada por user {auth.user_id}"
    )

    return new_org


@router.get("", response_model=list[OrganizationOut])
def list_organizations(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("member")),
):
    """
    Lista todas las organizaciones del Account del usuario.

    Retorna todas las organizaciones que pertenecen al mismo Account
    que la organización actual del usuario.
    """
    # Obtener el account_id del usuario actual
    current_org = (
        db.query(Organization).filter(Organization.id == auth.organization_id).first()
    )

    if not current_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización actual no encontrada",
        )

    # Obtener todas las organizaciones del account
    organizations = (
        db.query(Organization)
        .filter(
            Organization.account_id == current_org.account_id,
            Organization.status != OrganizationStatus.DELETED,
        )
        .order_by(Organization.created_at.desc())
        .all()
    )

    return organizations


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("member")),
):
    """
    Obtiene información de una organización específica.

    Solo permite acceder a organizaciones del mismo Account.
    """
    # Obtener el account_id del usuario actual
    current_org = (
        db.query(Organization).filter(Organization.id == auth.organization_id).first()
    )

    if not current_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización actual no encontrada",
        )

    # Obtener la organización solicitada
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    # Verificar que pertenece al mismo account
    if organization.account_id != current_org.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta organización",
        )

    return organization


@router.patch("/{organization_id}", response_model=OrganizationOut)
def update_organization(
    organization_id: UUID,
    data: OrganizationUpdate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("owner")),
):
    """
    Actualiza una organización.

    Solo usuarios con rol 'owner' pueden actualizar organizaciones.
    Solo permite actualizar organizaciones del mismo Account.
    """
    # Obtener el account_id del usuario actual
    current_org = (
        db.query(Organization).filter(Organization.id == auth.organization_id).first()
    )

    if not current_org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización actual no encontrada",
        )

    # Obtener la organización a actualizar
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    # Verificar que pertenece al mismo account
    if organization.account_id != current_org.account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a esta organización",
        )

    # Actualizar campos
    update_data = data.model_dump(exclude_unset=True)

    if "name" in update_data:
        organization.name = update_data["name"]

    if "billing_email" in update_data:
        organization.billing_email = update_data["billing_email"]

    if "country" in update_data:
        organization.country = update_data["country"]

    if "timezone" in update_data:
        organization.timezone = update_data["timezone"]

    organization.updated_at = utcnow()

    db.commit()
    db.refresh(organization)

    logger.info(
        f"[ORGANIZATION UPDATE] Organización {organization_id} actualizada por user {auth.user_id}"
    )

    return organization
