"""
Endpoints internos para gestión de accounts.

Estos endpoints están protegidos por tokens PASETO y están diseñados
para ser usados por aplicaciones administrativas internas como gac-web.

Requiere: Token PASETO con service="gac" y role="GAC_ADMIN"

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación)
Organization = Raíz operativa (permisos, uso diario)

Endpoints disponibles:
- GET /: Lista todos los accounts con estadísticas
- GET /stats: Estadísticas globales del sistema
- GET /{account_id}: Obtener un account por ID
- GET /{account_id}/organizations: Listar organizaciones del account
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_cognito_or_paseto
from app.db.session import get_db
from app.models.account import Account, AccountStatus
from app.models.account_user import AccountRole, AccountUser
from app.models.device import Device
from app.models.organization import Organization
from app.models.unit_device import UnitDevice
from app.models.user import User
from app.services.account_nexus_status import (
    get_account_nexus_status,
    get_accounts_nexus_status_map,
    get_organization_nexus_status,
)

router = APIRouter()

# Dependencia para autenticación PASETO (o Cognito para flexibilidad)
get_auth_for_internal_accounts = get_auth_cognito_or_paseto(
    required_service="gac",
    required_role="GAC_ADMIN",
)


@router.get("")
def list_all_accounts(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_accounts),
    status_filter: Optional[AccountStatus] = Query(
        None, alias="status", description="Filtrar por estado del account"
    ),
    search: Optional[str] = Query(
        None, description="Buscar por nombre (parcial, case-insensitive)"
    ),
    limit: int = Query(50, ge=1, le=200, description="Límite de resultados"),
    offset: int = Query(0, ge=0, description="Offset para paginación"),
):
    """
    Lista todos los accounts del sistema con estadísticas.

    Retorna para cada account:
    - account_name, billing_email, status, created_at, updated_at
    - owner_email: email del usuario owner
    - total_organizations: cantidad de organizaciones del account
    - total_users: cantidad de usuarios en todas las organizaciones del account
    """
    # Subquery para contar organizaciones por account
    org_count_subq = (
        db.query(
            Organization.account_id,
            func.count(Organization.id).label("org_count"),
        )
        .group_by(Organization.account_id)
        .subquery()
    )

    # Subquery para contar usuarios por account (a través de organizations)
    user_count_subq = (
        db.query(
            Organization.account_id,
            func.count(User.id).label("user_count"),
        )
        .join(User, User.organization_id == Organization.id)
        .group_by(Organization.account_id)
        .subquery()
    )

    # Subquery para obtener el email del owner (desde account_users)
    owner_subq = (
        db.query(
            AccountUser.account_id,
            User.email.label("owner_email"),
        )
        .join(User, User.id == AccountUser.user_id)
        .filter(AccountUser.role == AccountRole.OWNER.value)
        .distinct(AccountUser.account_id)
        .subquery()
    )

    # Query principal
    query = (
        db.query(
            Account.id,
            Account.name.label("account_name"),
            Account.billing_email,
            Account.status,
            Account.created_at,
            Account.updated_at,
            owner_subq.c.owner_email,
            func.coalesce(org_count_subq.c.org_count, 0).label("total_organizations"),
            func.coalesce(user_count_subq.c.user_count, 0).label("total_users"),
        )
        .outerjoin(org_count_subq, Account.id == org_count_subq.c.account_id)
        .outerjoin(user_count_subq, Account.id == user_count_subq.c.account_id)
        .outerjoin(owner_subq, Account.id == owner_subq.c.account_id)
    )

    # Aplicar filtros
    if status_filter:
        query = query.filter(Account.status == status_filter)

    if search:
        query = query.filter(Account.name.ilike(f"%{search}%"))

    # Ordenar y paginar
    query = query.order_by(Account.created_at.desc())
    query = query.offset(offset).limit(limit)

    # Ejecutar query
    results = query.all()

    account_ids = [row.id for row in results]
    nexus_by_account = get_accounts_nexus_status_map(db, account_ids)

    # Construir respuesta
    accounts = []
    for row in results:
        nexus = nexus_by_account.get(row.id, {})
        accounts.append(
            {
                "id": str(row.id),
                "account_name": row.account_name,
                "billing_email": row.billing_email,
                "status": row.status,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "owner_email": row.owner_email,
                "total_organizations": row.total_organizations,
                "total_users": row.total_users,
                **nexus,
            }
        )

    return accounts


# IMPORTANTE: /stats debe estar ANTES de /{account_id} para evitar que FastAPI
# interprete "stats" como un UUID
@router.get("/stats")
def get_accounts_stats(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_accounts),
):
    """
    Obtiene estadísticas globales del sistema.

    Retorna:
    - Conteo de accounts por estado
    - Total de devices y por estado
    - Devices instalados (asignados a unidades)
    - Total de usuarios
    """
    # Estadísticas de Accounts
    total_accounts = db.query(Account).count()
    accounts_active = (
        db.query(Account).filter(Account.status == AccountStatus.ACTIVE).count()
    )
    accounts_suspended = (
        db.query(Account).filter(Account.status == AccountStatus.SUSPENDED).count()
    )
    accounts_deleted = (
        db.query(Account).filter(Account.status == AccountStatus.DELETED).count()
    )

    # Estadísticas de Devices
    total_devices = db.query(Device).count()
    devices_nuevo = db.query(Device).filter(Device.status == "nuevo").count()
    devices_preparado = db.query(Device).filter(Device.status == "preparado").count()
    devices_enviado = db.query(Device).filter(Device.status == "enviado").count()
    devices_entregado = db.query(Device).filter(Device.status == "entregado").count()
    devices_asignado = db.query(Device).filter(Device.status == "asignado").count()
    devices_devuelto = db.query(Device).filter(Device.status == "devuelto").count()
    devices_inactivo = db.query(Device).filter(Device.status == "inactivo").count()

    # Devices instalados (asignados a unidades activas)
    devices_instalados = (
        db.query(UnitDevice).filter(UnitDevice.unassigned_at.is_(None)).count()
    )

    # Total de usuarios
    total_users = db.query(User).count()

    return {
        "accounts": {
            "total": total_accounts,
            "by_status": {
                "active": accounts_active,
                "suspended": accounts_suspended,
                "deleted": accounts_deleted,
            },
        },
        "devices": {
            "total": total_devices,
            "instalados": devices_instalados,
            "by_status": {
                "nuevo": devices_nuevo,
                "preparado": devices_preparado,
                "enviado": devices_enviado,
                "entregado": devices_entregado,
                "asignado": devices_asignado,
                "devuelto": devices_devuelto,
                "inactivo": devices_inactivo,
            },
        },
        "users": {
            "total": total_users,
        },
    }


@router.get("/{account_id}")
def get_account_by_id(
    account_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_accounts),
):
    """
    Obtiene un account específico por ID con estadísticas.

    Retorna:
    - account_name, billing_email, status, created_at, updated_at
    - owner_email: email del usuario owner
    - total_organizations: cantidad de organizaciones del account
    - total_users: cantidad de usuarios en todas las organizaciones del account
    """
    # Buscar el account
    account = db.query(Account).filter(Account.id == account_id).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account no encontrado",
        )

    # Contar organizaciones
    total_organizations = (
        db.query(func.count(Organization.id))
        .filter(Organization.account_id == account_id)
        .scalar()
    ) or 0

    # Contar usuarios (a través de organizations)
    total_users = (
        db.query(func.count(User.id))
        .join(Organization, User.organization_id == Organization.id)
        .filter(Organization.account_id == account_id)
        .scalar()
    ) or 0

    # Obtener email del owner
    owner_email = (
        db.query(User.email)
        .join(AccountUser, AccountUser.user_id == User.id)
        .filter(AccountUser.account_id == account_id)
        .filter(AccountUser.role == AccountRole.OWNER.value)
        .scalar()
    )

    return {
        "id": str(account.id),
        "account_name": account.name,
        "billing_email": account.billing_email,
        "status": account.status,
        "created_at": account.created_at.isoformat() if account.created_at else None,
        "updated_at": account.updated_at.isoformat() if account.updated_at else None,
        "owner_email": owner_email,
        "total_organizations": total_organizations,
        "total_users": total_users,
        **get_account_nexus_status(db, account_id),
    }


@router.get("/{account_id}/organizations")
def get_account_organizations(
    account_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_internal_accounts),
):
    """
    Lista todas las organizaciones de un account específico.

    Retorna para cada organización:
    - id, name, status, billing_email, country, timezone
    - total_users: cantidad de usuarios en la organización
    - created_at, updated_at
    """
    # Verificar que el account existe
    account = db.query(Account).filter(Account.id == account_id).first()

    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account no encontrado",
        )

    # Obtener organizaciones con conteo de usuarios
    organizations = (
        db.query(
            Organization.id,
            Organization.name,
            Organization.status,
            Organization.billing_email,
            Organization.country,
            Organization.timezone,
            Organization.created_at,
            Organization.updated_at,
            func.count(User.id).label("total_users"),
        )
        .outerjoin(User, User.organization_id == Organization.id)
        .filter(Organization.account_id == account_id)
        .group_by(Organization.id)
        .order_by(Organization.created_at.desc())
        .all()
    )

    return [
        {
            "id": str(org.id),
            "name": org.name,
            "status": org.status,
            "billing_email": org.billing_email,
            "country": org.country,
            "timezone": org.timezone,
            "total_users": org.total_users,
            "created_at": org.created_at.isoformat() if org.created_at else None,
            "updated_at": org.updated_at.isoformat() if org.updated_at else None,
            **get_organization_nexus_status(db, org.id),
        }
        for org in organizations
    ]
