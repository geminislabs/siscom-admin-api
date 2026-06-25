"""
Endpoints de Gestión de Accounts.

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación)
- Puede tener múltiples Organizations
- Controla la información comercial y de facturación

Organization = Raíz operativa (permisos, uso diario)

ENDPOINTS:
==========
- GET /accounts/organization: Obtiene la organización del usuario autenticado
- GET /accounts/{account_id}: Obtiene información del account
- PATCH /accounts/{account_id}: Actualiza perfil progresivo del account

NOTA:
- El registro se realiza en POST /auth/register
- Mi cuenta se obtiene en GET /auth/me

REGLA DE ORO:
=============
Los nombres NO son identidad. Los UUID sí.
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthResult,
    get_current_organization_id,
    get_current_user_full,
    require_organization_role,
)
from app.db.session import get_db
from app.models.account import Account
from app.models.organization import Organization
from app.models.user import User
from app.schemas.account import (
    AccountOut,
    AccountUpdate,
    AccountUpdateResponse,
)
from app.schemas.organization import OrganizationOut
from app.utils.datetime import utcnow

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/organization", response_model=OrganizationOut)
def get_current_organization(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    """
    Obtiene la información de la organización del usuario autenticado.

    Requiere autenticación con token de Cognito.
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


# ============================================
# Account Management - Endpoints Protegidos
# ============================================


@router.get("/{account_id}", response_model=AccountOut)
def get_account(
    account_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Obtiene información de un Account específico.

    Verifica que el usuario tenga acceso al account solicitado.
    """
    # Verificar que el account existe
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account no encontrado",
        )

    # Verificar que el usuario tiene acceso (su organización pertenece al account)
    user_org = (
        db.query(Organization)
        .filter(Organization.id == current_user.organization_id)
        .first()
    )

    if not user_org or user_org.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este account",
        )

    return account


@router.patch("/{account_id}", response_model=AccountUpdateResponse)
def update_account(
    account_id: UUID,
    data: AccountUpdate,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_role("owner")),
):
    """
    Actualiza el perfil de un Account (perfil progresivo).

    Este endpoint permite completar o actualizar la información del Account
    de forma progresiva. Todos los campos son opcionales.

    PERMISOS:
    =========
    Solo usuarios con rol 'owner' pueden modificar el Account.

    CAMPOS ACTUALIZABLES:
    =====================
    - account_name: Nombre de la cuenta/empresa (puede repetirse, NO unicidad)
    - billing_email: Email de facturación
    - country: Código de país ISO
    - timezone: Zona horaria IANA
    - metadata: Metadatos adicionales

    VALIDACIONES:
    =============
    ❌ NO se exigen campos fiscales
    ❌ NO se valida unicidad por nombre
    ✅ billing_email puede ser único si existe

    Returns:
        AccountUpdateResponse con información actualizada
    """
    # Verificar que el account existe
    account = db.query(Account).filter(Account.id == account_id).first()
    if not account:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Account no encontrado",
        )

    # Verificar que el usuario pertenece a una organización de este account
    user_org = (
        db.query(Organization).filter(Organization.id == auth.organization_id).first()
    )

    if not user_org or user_org.account_id != account_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes acceso a este account",
        )

    # Actualizar solo los campos proporcionados
    update_data = data.model_dump(exclude_unset=True)

    if "account_name" in update_data:
        account.name = update_data["account_name"]
        # También actualizar nombre de la organización default si coincide
        if user_org.name == account.name or not user_org.name:
            user_org.name = update_data["account_name"]

    if "billing_email" in update_data:
        account.billing_email = update_data["billing_email"]
        # Propagar a la organización
        user_org.billing_email = update_data["billing_email"]

    # Actualizar timestamp
    account.updated_at = utcnow()
    user_org.updated_at = utcnow()

    db.commit()
    db.refresh(account)

    logger.info(
        f"[ACCOUNT UPDATE] Account {account_id} actualizado por user {auth.user_id}"
    )

    return AccountUpdateResponse(
        id=account.id,
        account_name=account.name,
        billing_email=account.billing_email,
        updated_at=account.updated_at,
    )
