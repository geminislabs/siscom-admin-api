"""
Endpoints internos para gestión de organizaciones.

Estos endpoints están protegidos por tokens PASETO y están diseñados
para ser usados por aplicaciones administrativas internas como gac-web.

Requiere: Token PASETO con service="gac" y role="GAC_ADMIN"

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación)
Organization = Raíz operativa (permisos, uso diario)
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_cognito_or_paseto
from app.db.session import get_db
from app.models.account import Account
from app.models.organization import Organization, OrganizationStatus
from app.models.user import User
from app.schemas.organization import (
    InternalOrganizationCreate,
    OrganizationOut,
    OrganizationUpdate,
)
from app.services.account_nexus_status import get_organization_nexus_status

router = APIRouter()

# Dependencia para autenticación PASETO (o Cognito para flexibilidad)
get_auth_for_internal_organizations = get_auth_cognito_or_paseto(
    required_service="gac",
    required_role="GAC_ADMIN",
)


@router.get("", response_model=list[OrganizationOut])
def list_all_organizations(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
    status_filter: Optional[OrganizationStatus] = Query(
        None, alias="status", description="Filtrar por estado de la organización"
    ),
    search: Optional[str] = Query(
        None, description="Buscar por nombre (parcial, case-insensitive)"
    ),
    account_id: Optional[UUID] = Query(
        None, description="Filtrar por cuenta (account_id)"
    ),
    limit: int = Query(50, ge=1, le=200, description="Límite de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
):
    """
    Lista todas las organizaciones del sistema.

    Solo accesible para administradores internos con token PASETO válido.

    Parámetros de filtrado:
    - status: Filtrar por estado (PENDING, ACTIVE, SUSPENDED, DELETED)
    - search: Buscar por nombre (búsqueda parcial)
    - limit: Máximo de resultados (default: 50, max: 200)
    - offset: Para paginación
    """
    query = db.query(Organization)

    # Aplicar filtros
    if status_filter:
        query = query.filter(Organization.status == status_filter)

    if search:
        query = query.filter(Organization.name.ilike(f"%{search}%"))

    if account_id:
        query = query.filter(Organization.account_id == account_id)

    # Ordenar por fecha de creación descendente
    query = query.order_by(Organization.created_at.desc())

    # Aplicar paginación
    organizations = query.offset(offset).limit(limit).all()

    return organizations


@router.get("/stats")
def get_organizations_stats(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
):
    """
    Obtiene estadísticas generales de las organizaciones.

    Retorna conteo por estado y total de organizaciones.
    """
    total = db.query(Organization).count()
    pending = (
        db.query(Organization)
        .filter(Organization.status == OrganizationStatus.PENDING)
        .count()
    )
    active = (
        db.query(Organization)
        .filter(Organization.status == OrganizationStatus.ACTIVE)
        .count()
    )
    suspended = (
        db.query(Organization)
        .filter(Organization.status == OrganizationStatus.SUSPENDED)
        .count()
    )
    deleted = (
        db.query(Organization)
        .filter(Organization.status == OrganizationStatus.DELETED)
        .count()
    )

    return {
        "total": total,
        "by_status": {
            "pending": pending,
            "active": active,
            "suspended": suspended,
            "deleted": deleted,
        },
    }


@router.post("", response_model=OrganizationOut, status_code=status.HTTP_201_CREATED)
def create_organization_for_account(
    data: InternalOrganizationCreate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
):
    """
    Crea una organización bajo una cuenta existente (staff GAC).
    No requiere sesión Cognito del cliente.
    """
    account = db.query(Account).filter(Account.id == data.account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account no encontrado",
        )

    new_org = Organization(
        account_id=data.account_id,
        name=data.name,
        billing_email=data.billing_email,
        country=data.country or "MX",
        timezone=data.timezone or "America/Mexico_City",
        status=OrganizationStatus.ACTIVE,
    )
    db.add(new_org)
    db.commit()
    db.refresh(new_org)
    return new_org


@router.get("/{organization_id}", response_model=OrganizationOut)
def get_organization_by_id(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
):
    """
    Obtiene una organización específica por su ID.

    Solo accesible para administradores internos con token PASETO válido.
    """
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    return organization


@router.get("/{organization_id}/nexus-status")
def get_organization_nexus_status_endpoint(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
):
    """Resumen de suscripción Nexus activa para la organización."""
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )
    return get_organization_nexus_status(db, organization_id)


@router.patch("/{organization_id}", response_model=OrganizationOut)
def update_organization_metadata(
    organization_id: UUID,
    data: OrganizationUpdate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
):
    """Actualiza metadatos de la organización (nombre, billing, timezone)."""
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    update_data = data.model_dump(exclude_unset=True)
    for field in ("name", "billing_email", "country", "timezone"):
        if field in update_data:
            setattr(organization, field, update_data[field])

    organization.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(organization)
    return organization


@router.get("/{organization_id}/users")
def get_organization_users(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
):
    """
    Lista todos los usuarios de una organización específica.

    Útil para administración y soporte.
    """
    # Verificar que la organización existe
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    users = db.query(User).filter(User.organization_id == organization_id).all()

    return [
        {
            "id": str(user.id),
            "email": user.email,
            "full_name": user.full_name,
            "is_master": user.is_master,
            "email_verified": user.email_verified,
            "has_cognito": user.cognito_sub is not None,
            "created_at": user.created_at.isoformat() if user.created_at else None,
        }
        for user in users
    ]


@router.patch("/{organization_id}/status")
def update_organization_status(
    organization_id: UUID,
    new_status: OrganizationStatus,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_organizations),
):
    """
    Actualiza el estado de una organización.

    Permite suspender, activar o marcar como eliminada una organización.

    Estados válidos:
    - PENDING: Organización pendiente de verificación
    - ACTIVE: Organización activa
    - SUSPENDED: Organización suspendida
    - DELETED: Organización eliminada lógicamente
    """
    organization = (
        db.query(Organization).filter(Organization.id == organization_id).first()
    )

    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organización no encontrada",
        )

    old_status = organization.status
    organization.status = new_status
    db.commit()
    db.refresh(organization)

    return {
        "message": f"Estado actualizado de {old_status} a {new_status}",
        "organization": {
            "id": str(organization.id),
            "name": organization.name,
            "status": organization.status,
        },
    }
