"""
Servicio de Resolución de Capabilities.

Este es el PUNTO ÚNICO de resolución de capabilities del sistema.
Implementa la regla de oro:

    organization_capability_override ?? plan_capability ?? default

USO:
    from app.services.capabilities import CapabilityService
    # Obtener una capability específica
    max_devices = CapabilityService.get_capability(db, org_id, "max_devices")
    # Verificar si tiene una feature
    has_ai = CapabilityService.has_capability(db, org_id, "ai_features")
    # Validar límite antes de crear
    if not CapabilityService.validate_limit(db, org_id, "max_geofences", current_count):
        raise HTTPException(403, "Límite de geocercas alcanzado")
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Union
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.capability import Capability, OrganizationCapability, PlanCapability
from app.services.subscription_query import get_active_plan_id as _get_active_plan_id
from app.utils.datetime import utcnow


@dataclass
class ResolvedCapability:
    """
    Resultado de la resolución de una capability.

    Attributes:
        code: Código de la capability
        value: Valor resuelto (int, bool, o str)
        source: Origen del valor ('organization', 'plan', 'default')
        plan_id: ID del plan de donde se obtuvo (si aplica)
        expires_at: Fecha de expiración del override (si aplica)
    """

    code: str
    value: Union[int, bool, str, None]
    source: str  # 'organization', 'plan', 'default'
    plan_id: Optional[UUID] = None
    expires_at: Optional[datetime] = None

    def as_int(self) -> int:
        """Retorna el valor como entero."""
        if isinstance(self.value, int):
            return self.value
        if isinstance(self.value, bool):
            return 1 if self.value else 0
        return int(self.value) if self.value else 0

    def as_bool(self) -> bool:
        """Retorna el valor como booleano."""
        if isinstance(self.value, bool):
            return self.value
        if isinstance(self.value, int):
            return self.value > 0
        if isinstance(self.value, str):
            return self.value.lower() in ("true", "1", "yes", "enabled")
        return False


# Valores por defecto para capabilities conocidas
DEFAULT_CAPABILITIES: dict[str, Any] = {
    # Límites
    "max_devices": 1,
    "max_geofences": 5,
    "max_users": 3,
    "history_days": 7,
    # Features
    "ai_features": False,
    "analytics_tools": False,
    "real_time_tracking": True,
    "alerts_enabled": True,
    "reports_enabled": True,
    "api_access": False,
}


class CapabilityService:
    """
    Servicio centralizado para resolución de capabilities.

    Regla de resolución:
    1. Si existe override de organización (no expirado) → usar override
    2. Si existe en plan_capabilities del plan activo → usar plan
    3. Si existe valor por defecto → usar default
    4. Si no existe → None
    """

    @staticmethod
    def get_active_plan_id(db: Session, organization_id: UUID) -> Optional[UUID]:
        """
        Obtiene el plan_id de la suscripción activa de la organización.

        DELEGACIÓN: Esta función delega a subscription_query.get_active_plan_id()
        que es la ÚNICA fuente de verdad para la regla de suscripción activa.

        Si hay múltiples suscripciones activas, retorna la de la más reciente por started_at.
        """
        return _get_active_plan_id(db, organization_id)

    @staticmethod
    def get_capability(
        db: Session,
        organization_id: UUID,
        capability_code: str,
    ) -> ResolvedCapability:
        """
        Resuelve una capability para una organización.

        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            capability_code: Código de la capability (ej: "max_devices")

        Returns:
            ResolvedCapability con el valor y metadatos
        """
        _now = utcnow()

        # 1. Buscar la definición de la capability
        capability = (
            db.query(Capability).filter(Capability.code == capability_code).first()
        )

        if not capability:
            # Capability no existe, usar default si lo hay
            default_value = DEFAULT_CAPABILITIES.get(capability_code)
            return ResolvedCapability(
                code=capability_code, value=default_value, source="default"
            )

        # 2. Buscar override de organización (no expirado)
        org_override = (
            db.query(OrganizationCapability)
            .filter(
                OrganizationCapability.organization_id == organization_id,
                OrganizationCapability.capability_id == capability.id,
            )
            .first()
        )

        if org_override and not org_override.is_expired():
            return ResolvedCapability(
                code=capability_code,
                value=org_override.get_value(),
                source="organization",
                expires_at=org_override.expires_at,
            )

        # 3. Buscar en plan de suscripción activa
        plan_id = CapabilityService.get_active_plan_id(db, organization_id)

        if plan_id:
            plan_cap = (
                db.query(PlanCapability)
                .filter(
                    PlanCapability.plan_id == plan_id,
                    PlanCapability.capability_id == capability.id,
                )
                .first()
            )

            if plan_cap:
                return ResolvedCapability(
                    code=capability_code,
                    value=plan_cap.get_value(),
                    source="plan",
                    plan_id=plan_id,
                )

        # 4. Usar valor por defecto
        default_value = DEFAULT_CAPABILITIES.get(capability_code)
        return ResolvedCapability(
            code=capability_code, value=default_value, source="default"
        )

    @staticmethod
    def get_all_capabilities(
        db: Session,
        organization_id: UUID,
    ) -> dict[str, ResolvedCapability]:
        """
        Obtiene todas las capabilities resueltas para una organización.

        Returns:
            Diccionario con código -> ResolvedCapability
        """
        result = {}

        # Obtener todas las capabilities definidas
        capabilities = db.query(Capability).all()

        for cap in capabilities:
            resolved = CapabilityService.get_capability(db, organization_id, cap.code)
            result[cap.code] = resolved

        # Agregar defaults que no están en la BD
        for code, default_value in DEFAULT_CAPABILITIES.items():
            if code not in result:
                result[code] = ResolvedCapability(
                    code=code, value=default_value, source="default"
                )

        return result

    @staticmethod
    def has_capability(
        db: Session,
        organization_id: UUID,
        capability_code: str,
    ) -> bool:
        """
        Verifica si una organización tiene habilitada una capability booleana.

        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            capability_code: Código de la capability

        Returns:
            True si la capability está habilitada
        """
        resolved = CapabilityService.get_capability(
            db, organization_id, capability_code
        )
        return resolved.as_bool()

    @staticmethod
    def get_limit(
        db: Session,
        organization_id: UUID,
        capability_code: str,
    ) -> int:
        """
        Obtiene el límite numérico de una capability.

        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            capability_code: Código de la capability

        Returns:
            El límite como entero
        """
        resolved = CapabilityService.get_capability(
            db, organization_id, capability_code
        )
        return resolved.as_int()

    @staticmethod
    def validate_limit(
        db: Session,
        organization_id: UUID,
        capability_code: str,
        current_count: int,
    ) -> bool:
        """
        Valida si se puede agregar un elemento más sin exceder el límite.

        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            capability_code: Código de la capability de límite
            current_count: Cantidad actual de elementos

        Returns:
            True si se puede agregar uno más
        """
        limit = CapabilityService.get_limit(db, organization_id, capability_code)

        # Si el límite es 0 o negativo, se considera ilimitado
        if limit <= 0:
            return True

        return current_count < limit

    @staticmethod
    def get_capabilities_summary(
        db: Session,
        organization_id: UUID,
    ) -> dict:
        """
        Obtiene un resumen de capabilities para mostrar al usuario.

        Returns:
            Diccionario con límites y features agrupados
        """
        all_caps = CapabilityService.get_all_capabilities(db, organization_id)

        limits = {}
        features = {}

        for code, resolved in all_caps.items():
            if isinstance(resolved.value, bool):
                features[code] = resolved.value
            elif isinstance(resolved.value, int):
                limits[code] = resolved.value
            else:
                features[code] = resolved.value

        return {
            "limits": limits,
            "features": features,
        }


# =====================================================
# Funciones de conveniencia para uso directo
# =====================================================


def get_capability(db: Session, organization_id: UUID, code: str) -> ResolvedCapability:
    """Atajo para CapabilityService.get_capability"""
    return CapabilityService.get_capability(db, organization_id, code)


def has_capability(db: Session, organization_id: UUID, code: str) -> bool:
    """Atajo para CapabilityService.has_capability"""
    return CapabilityService.has_capability(db, organization_id, code)


def validate_limit(db: Session, organization_id: UUID, code: str, current: int) -> bool:
    """Atajo para CapabilityService.validate_limit"""
    return CapabilityService.validate_limit(db, organization_id, code, current)


# =====================================================
# Aliases de compatibilidad (DEPRECATED)
# =====================================================


def get_capability_for_client(
    db: Session, client_id: UUID, code: str
) -> ResolvedCapability:
    """DEPRECATED: Usar get_capability con organization_id"""
    return get_capability(db, client_id, code)


def has_capability_for_client(db: Session, client_id: UUID, code: str) -> bool:
    """DEPRECATED: Usar has_capability con organization_id"""
    return has_capability(db, client_id, code)


def validate_limit_for_client(
    db: Session, client_id: UUID, code: str, current: int
) -> bool:
    """DEPRECATED: Usar validate_limit con organization_id"""
    return validate_limit(db, client_id, code, current)
