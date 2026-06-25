"""
Módulo Central de Queries de Suscripciones.

Este módulo define la ÚNICA regla para determinar qué suscripciones están activas.
Todos los servicios que necesiten conocer el estado de suscripciones deben usar
estas funciones.

MODELO CONCEPTUAL:
==================
Las suscripciones pertenecen a ORGANIZATIONS (raíz operativa).
Los pagos pertenecen a ACCOUNTS (raíz comercial).

REGLA DE SUSCRIPCIÓN ACTIVA:
----------------------------
Una suscripción se considera activa si cumple TODAS las siguientes condiciones:
1. status IN ('ACTIVE', 'TRIAL')
2. expires_at > now() OR expires_at IS NULL

Si hay múltiples suscripciones activas, la estrategia es:
- Para obtener UNA: la más reciente por started_at (ORDER BY started_at DESC LIMIT 1)
- Para obtener TODAS: ordenadas por started_at DESC

NOTA: El campo `active_subscription_id` en `organizations` es LEGACY y NO se usa como
fuente de verdad. El estado activo siempre se calcula dinámicamente.
"""

from typing import Optional
from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Query, Session

from app.models.subscription import Subscription, SubscriptionStatus
from app.utils.datetime import utcnow


def _build_active_subscriptions_query(
    db: Session,
    organization_id: UUID,
) -> Query:
    """
    Construye la query base para suscripciones activas.

    Esta función encapsula la ÚNICA definición de qué es una suscripción activa.

    Args:
        db: Sesión de base de datos
        organization_id: ID de la organización

    Returns:
        Query configurada para filtrar suscripciones activas
    """
    now = utcnow()

    return (
        db.query(Subscription)
        .filter(
            Subscription.organization_id == organization_id,
            # Condición 1: Status debe ser ACTIVE o TRIAL
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value]
            ),
            # Condición 2: No debe estar expirada
            # expires_at > now OR expires_at IS NULL (suscripción sin expiración)
            or_(Subscription.expires_at > now, Subscription.expires_at.is_(None)),
        )
        .order_by(Subscription.started_at.desc())
    )


def get_active_subscriptions(
    db: Session,
    organization_id: UUID,
) -> list[Subscription]:
    """
    Obtiene TODAS las suscripciones activas de una organización.

    Útil cuando se necesita ver todas las suscripciones vigentes
    (por ejemplo, para mostrar en dashboard o para auditoría).

    Args:
        db: Sesión de base de datos
        organization_id: ID de la organización

    Returns:
        Lista de suscripciones activas, ordenadas por started_at DESC (más reciente primero)
    """
    return _build_active_subscriptions_query(db, organization_id).all()


def get_primary_active_subscription(
    db: Session,
    organization_id: UUID,
) -> Optional[Subscription]:
    """
    Obtiene la suscripción activa PRINCIPAL de una organización.

    ESTRATEGIA DE SELECCIÓN:
    ------------------------
    Cuando existen múltiples suscripciones activas para una organización,
    el sistema selecciona como suscripción principal la más reciente según `started_at`.

    Esta suscripción se usa para:
    - Determinar el plan a mostrar en billing/UI
    - Resolver capabilities desde plan_capabilities (si no hay override)
    - Calcular próxima fecha de cobro

    Esta suscripción NO determina:
    - Las capabilities finales (pueden venir de organization_capabilities override)
    - Que la organización solo pueda tener una suscripción
    - Restricciones operativas del sistema

    NOTA: Esta es una regla de PRESENTACIÓN, no una limitación de negocio.
    Las capabilities se resuelven de forma independiente en CapabilityService.

    Args:
        db: Sesión de base de datos
        organization_id: ID de la organización

    Returns:
        La suscripción activa principal (más reciente por started_at),
        o None si no hay ninguna suscripción activa
    """
    return _build_active_subscriptions_query(db, organization_id).first()


def get_active_plan_id(
    db: Session,
    organization_id: UUID,
) -> Optional[UUID]:
    """
    Obtiene el plan_id de la suscripción activa principal.

    Esta es la función que debe usar CapabilityService para
    resolver capabilities basadas en el plan.

    Args:
        db: Sesión de base de datos
        organization_id: ID de la organización

    Returns:
        UUID del plan de la suscripción activa, o None si no hay suscripción activa
    """
    subscription = get_primary_active_subscription(db, organization_id)
    return subscription.plan_id if subscription else None


def has_active_subscription(
    db: Session,
    organization_id: UUID,
) -> bool:
    """
    Verifica si una organización tiene al menos una suscripción activa.

    Args:
        db: Sesión de base de datos
        organization_id: ID de la organización

    Returns:
        True si tiene al menos una suscripción activa
    """
    return _build_active_subscriptions_query(db, organization_id).first() is not None


def get_subscription_history(
    db: Session,
    organization_id: UUID,
    limit: int = 20,
) -> list[Subscription]:
    """
    Obtiene el historial completo de suscripciones de una organización.

    Incluye suscripciones activas, canceladas y expiradas.

    Args:
        db: Sesión de base de datos
        organization_id: ID de la organización
        limit: Número máximo de resultados

    Returns:
        Lista de todas las suscripciones, ordenadas por created_at DESC
    """
    return (
        db.query(Subscription)
        .filter(Subscription.organization_id == organization_id)
        .order_by(Subscription.created_at.desc())
        .limit(limit)
        .all()
    )


def count_active_subscriptions(
    db: Session,
    organization_id: UUID,
) -> int:
    """
    Cuenta el número de suscripciones activas de una organización.

    Args:
        db: Sesión de base de datos
        organization_id: ID de la organización

    Returns:
        Número de suscripciones activas
    """
    return _build_active_subscriptions_query(db, organization_id).count()


# =====================================================
# Aliases de compatibilidad (DEPRECATED)
# =====================================================


def get_active_subscriptions_for_client(
    db: Session, client_id: UUID
) -> list[Subscription]:
    """DEPRECATED: Usar get_active_subscriptions con organization_id"""
    return get_active_subscriptions(db, client_id)


def get_primary_active_subscription_for_client(
    db: Session, client_id: UUID
) -> Optional[Subscription]:
    """DEPRECATED: Usar get_primary_active_subscription con organization_id"""
    return get_primary_active_subscription(db, client_id)


def has_active_subscription_for_client(db: Session, client_id: UUID) -> bool:
    """DEPRECATED: Usar has_active_subscription con organization_id"""
    return has_active_subscription(db, client_id)
