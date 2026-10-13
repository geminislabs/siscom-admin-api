"""
Endpoints de Gestión de Capabilities de Organizaciones.

Endpoints:
- GET    /organizations/{organization_id}/capabilities
- POST   /organizations/{organization_id}/capabilities
- DELETE /organizations/{organization_id}/capabilities/{capability_code}

Las capabilities se resuelven con la regla:
    organization_override ?? plan_capability ?? default

NOTA: Estos endpoints gestionan los OVERRIDES de organización.
Para ver capabilities efectivas también puede usarse /capabilities
"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, require_organization_permission
from app.db.session import get_db
from app.models.capability import Capability, OrganizationCapability
from app.models.organization import Organization
from app.schemas.capability import (
    EffectiveCapabilityOut,
    OrganizationCapabilitiesListOut,
    OrganizationCapabilityCreate,
    OrganizationCapabilityOut,
)
from app.services.audit import AuditService
from app.services.capabilities import CapabilityService

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
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


def _get_capability_by_code(db: Session, code: str) -> Capability:
    """
    Obtiene una capability por su código.

    Raises:
        HTTPException 404 si no existe
    """
    capability = db.query(Capability).filter(Capability.code == code).first()
    if not capability:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Capability '{code}' no encontrada",
        )
    return capability


# =============================================================================
# Endpoints
# =============================================================================


@router.get(
    "/{organization_id}/capabilities",
    response_model=OrganizationCapabilitiesListOut,
)
def list_organization_capabilities(
    organization_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(require_organization_permission("capabilities.read")),
):
    """
    Lista todas las capabilities efectivas de una organización.

    Retorna las capabilities resueltas con su fuente:
    - organization: Override específico de la organización
    - plan: Valor del plan activo
    - default: Valor por defecto del sistema

    Cualquier miembro puede ver las capabilities.
    """
    # Verificar acceso
    _verify_org_access(db, organization_id, auth)

    # Obtener todas las capabilities resueltas
    all_caps = CapabilityService.get_all_capabilities(db, organization_id)

    # Obtener definiciones de capabilities para el value_type
    cap_definitions = {c.code: c for c in db.query(Capability).all()}

    capabilities = []
    overrides_count = 0

    for code, resolved in all_caps.items():
        cap_def = cap_definitions.get(code)
        value_type = cap_def.value_type if cap_def else "text"

        is_override = resolved.source == "organization"
        if is_override:
            overrides_count += 1

        capabilities.append(
            EffectiveCapabilityOut(
                code=code,
                value=resolved.value,
                value_type=value_type,
                source=resolved.source,
                plan_id=resolved.plan_id,
                expires_at=resolved.expires_at,
                is_override=is_override,
            )
        )

    # Ordenar por código
    capabilities.sort(key=lambda c: c.code)

    return OrganizationCapabilitiesListOut(
        capabilities=capabilities,
        total=len(capabilities),
        overrides_count=overrides_count,
    )


@router.post(
    "/{organization_id}/capabilities",
    response_model=OrganizationCapabilityOut,
    status_code=status.HTTP_201_CREATED,
)
def create_or_update_capability_override(
    organization_id: UUID,
    data: OrganizationCapabilityCreate,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(
        require_organization_permission("capabilities.override")
    ),
):
    """
    Crea o actualiza un override de capability para la organización.

    Exige `capabilities.override`, que desde la migración 041 no tiene ningún
    rol: un override es una decisión comercial y el owner no puede dárselo a
    su propia organización. Responde 403 a todos hasta que exista una ruta
    interna para GAC.

    Si ya existe un override para esta capability, se actualiza.
    Si no existe, se crea uno nuevo.

    El valor debe proporcionarse en el campo correspondiente al tipo:
    - value_int: Para capabilities de tipo int
    - value_bool: Para capabilities de tipo bool
    - value_text: Para capabilities de tipo text
    """
    # Verificar acceso
    org = _verify_org_access(db, organization_id, auth)

    # Obtener la capability
    capability = _get_capability_by_code(db, data.capability_code)

    # Determinar el valor según el tipo
    value = None
    if data.value_int is not None:
        value = data.value_int
    elif data.value_bool is not None:
        value = data.value_bool
    elif data.value_text is not None:
        value = data.value_text

    if value is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debe proporcionar un valor (value_int, value_bool o value_text)",
        )

    # Buscar override existente
    existing = (
        db.query(OrganizationCapability)
        .filter(
            OrganizationCapability.organization_id == organization_id,
            OrganizationCapability.capability_id == capability.id,
        )
        .first()
    )

    if existing:
        # Actualizar
        old_value = existing.get_value()

        existing.value_int = data.value_int
        existing.value_bool = data.value_bool
        existing.value_text = data.value_text
        existing.reason = data.reason
        existing.expires_at = data.expires_at

        # Registrar evento de actualización
        AuditService.log_org_capability_updated(
            db=db,
            account_id=org.account_id,
            organization_id=organization_id,
            actor_user_id=auth.user_id,
            capability_id=capability.id,
            capability_code=capability.code,
            old_value=old_value,
            new_value=value,
            reason=data.reason,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        db.commit()
        db.refresh(existing)

        logger.info(
            f"[ORG_CAP UPDATE] org={organization_id} capability={capability.code} "
            f"value changed from {old_value} to {value} by actor={auth.user_id}"
        )

        return OrganizationCapabilityOut(
            organization_id=organization_id,
            capability_id=capability.id,
            capability_code=capability.code,
            value=existing.get_value(),
            value_type=capability.value_type,
            source="organization",
            reason=existing.reason,
            expires_at=existing.expires_at,
        )

    else:
        # Crear nuevo
        org_cap = OrganizationCapability(
            organization_id=organization_id,
            capability_id=capability.id,
            value_int=data.value_int,
            value_bool=data.value_bool,
            value_text=data.value_text,
            reason=data.reason,
            expires_at=data.expires_at,
        )
        db.add(org_cap)

        # Registrar evento de creación
        AuditService.log_org_capability_created(
            db=db,
            account_id=org.account_id,
            organization_id=organization_id,
            actor_user_id=auth.user_id,
            capability_id=capability.id,
            capability_code=capability.code,
            value=value,
            reason=data.reason,
            ip_address=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )

        db.commit()
        db.refresh(org_cap)

        logger.info(
            f"[ORG_CAP CREATE] org={organization_id} capability={capability.code} "
            f"value={value} by actor={auth.user_id}"
        )

        return OrganizationCapabilityOut(
            organization_id=organization_id,
            capability_id=capability.id,
            capability_code=capability.code,
            value=org_cap.get_value(),
            value_type=capability.value_type,
            source="organization",
            reason=org_cap.reason,
            expires_at=org_cap.expires_at,
        )


@router.delete(
    "/{organization_id}/capabilities/{capability_code}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_capability_override(
    organization_id: UUID,
    capability_code: str,
    request: Request,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(
        require_organization_permission("capabilities.override")
    ),
):
    """
    Elimina un override de capability de la organización.

    Exige `capabilities.override`, que desde la migración 041 no tiene ningún
    rol: un override es una decisión comercial y el owner no puede dárselo a
    su propia organización. Responde 403 a todos hasta que exista una ruta
    interna para GAC.

    Al eliminar el override, la organización volverá a usar
    el valor del plan activo o el valor por defecto.
    """
    # Verificar acceso
    org = _verify_org_access(db, organization_id, auth)

    # Obtener la capability
    capability = _get_capability_by_code(db, capability_code)

    # Buscar el override
    org_cap = (
        db.query(OrganizationCapability)
        .filter(
            OrganizationCapability.organization_id == organization_id,
            OrganizationCapability.capability_id == capability.id,
        )
        .first()
    )

    if not org_cap:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Override de capability '{capability_code}' no encontrado",
        )

    previous_value = org_cap.get_value()

    # Registrar evento de eliminación ANTES de eliminar
    AuditService.log_org_capability_deleted(
        db=db,
        account_id=org.account_id,
        organization_id=organization_id,
        actor_user_id=auth.user_id,
        capability_id=capability.id,
        capability_code=capability.code,
        previous_value=previous_value,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    # Eliminar el override
    db.delete(org_cap)
    db.commit()

    logger.info(
        f"[ORG_CAP DELETE] org={organization_id} capability={capability_code} "
        f"(was value={previous_value}) by actor={auth.user_id}"
    )

    return None
