"""
Endpoints de Suscripciones.

Permite a las organizaciones:
- Ver sus suscripciones activas e históricas
- Cancelar suscripciones
- Ver detalles de suscripción

Las suscripciones activas se CALCULAN dinámicamente.
Una organización puede tener MÚLTIPLES suscripciones.

MODELO CONCEPTUAL:
==================
Las suscripciones pertenecen a ORGANIZATIONS (raíz operativa).
Los pagos pertenecen a ACCOUNTS (raíz comercial).
"""

from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    AuthResult,
    get_current_organization_id,
    require_billing_access,
)
from app.db.session import get_db
from app.models.plan import Plan
from app.models.subscription import Subscription, SubscriptionStatus
from app.schemas.subscription import (
    SubscriptionCancelRequest,
    SubscriptionOut,
    SubscriptionsListOut,
    SubscriptionWithPlanOut,
)
from app.utils.datetime import utcnow

router = APIRouter()


@router.get("", response_model=SubscriptionsListOut)
def list_subscriptions(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
    include_history: bool = Query(
        True, description="Incluir suscripciones históricas (canceladas/expiradas)"
    ),
    limit: int = Query(20, ge=1, le=100, description="Límite de resultados"),
):
    """
    Lista las suscripciones de la organización.

    Retorna:
    - Suscripciones activas (ACTIVE, TRIAL)
    - Opcionalmente, suscripciones históricas (CANCELLED, EXPIRED)
    """
    now = utcnow()

    query = db.query(Subscription).filter(
        Subscription.organization_id == organization_id
    )

    if not include_history:
        query = query.filter(
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value]
            )
        )

    subscriptions = query.order_by(Subscription.created_at.desc()).limit(limit).all()

    result = []
    active_count = 0

    for sub in subscriptions:
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()

        is_active = sub.status in [
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.TRIAL.value,
        ] and (sub.expires_at is None or sub.expires_at > now)

        if is_active:
            active_count += 1

        days_remaining = None
        if sub.expires_at:
            delta = sub.expires_at - now
            days_remaining = max(0, delta.days)

        result.append(
            SubscriptionWithPlanOut(
                id=sub.id,
                organization_id=sub.organization_id,
                plan_id=sub.plan_id,
                status=sub.status,
                billing_cycle=sub.billing_cycle,
                started_at=sub.started_at,
                expires_at=sub.expires_at,
                cancelled_at=sub.cancelled_at,
                renewed_from=sub.renewed_from,
                auto_renew=sub.auto_renew,
                external_id=sub.external_id,
                current_period_start=sub.current_period_start,
                current_period_end=sub.current_period_end,
                created_at=sub.created_at,
                updated_at=sub.updated_at,
                plan_name=plan.name if plan else None,
                plan_code=plan.code if plan else None,
                days_remaining=days_remaining,
                is_active=is_active,
            )
        )

    return SubscriptionsListOut(
        subscriptions=result,
        active_count=active_count,
        total_count=len(result),
    )


@router.get("/active", response_model=List[SubscriptionWithPlanOut])
def list_active_subscriptions(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    """
    Lista solo las suscripciones activas de la organización.

    Una suscripción está activa si:
    - status = ACTIVE o TRIAL
    - expires_at > now() o expires_at es NULL
    """
    now = utcnow()

    subscriptions = (
        db.query(Subscription)
        .filter(
            Subscription.organization_id == organization_id,
            Subscription.status.in_(
                [SubscriptionStatus.ACTIVE.value, SubscriptionStatus.TRIAL.value]
            ),
            Subscription.expires_at > now,
        )
        .order_by(Subscription.started_at.desc())
        .all()
    )

    result = []
    for sub in subscriptions:
        plan = db.query(Plan).filter(Plan.id == sub.plan_id).first()

        days_remaining = None
        if sub.expires_at:
            delta = sub.expires_at - now
            days_remaining = max(0, delta.days)

        result.append(
            SubscriptionWithPlanOut(
                id=sub.id,
                organization_id=sub.organization_id,
                plan_id=sub.plan_id,
                status=sub.status,
                billing_cycle=sub.billing_cycle,
                started_at=sub.started_at,
                expires_at=sub.expires_at,
                cancelled_at=sub.cancelled_at,
                renewed_from=sub.renewed_from,
                auto_renew=sub.auto_renew,
                external_id=sub.external_id,
                current_period_start=sub.current_period_start,
                current_period_end=sub.current_period_end,
                created_at=sub.created_at,
                updated_at=sub.updated_at,
                plan_name=plan.name if plan else None,
                plan_code=plan.code if plan else None,
                days_remaining=days_remaining,
                is_active=True,
            )
        )

    return result


@router.get("/{subscription_id}", response_model=SubscriptionWithPlanOut)
def get_subscription(
    subscription_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    """
    Obtiene los detalles de una suscripción específica.
    """
    now = utcnow()

    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.id == subscription_id,
            Subscription.organization_id == organization_id,
        )
        .first()
    )

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suscripción no encontrada",
        )

    plan = db.query(Plan).filter(Plan.id == subscription.plan_id).first()

    is_active = subscription.status in [
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.TRIAL.value,
    ] and (subscription.expires_at is None or subscription.expires_at > now)

    days_remaining = None
    if subscription.expires_at:
        delta = subscription.expires_at - now
        days_remaining = max(0, delta.days)

    return SubscriptionWithPlanOut(
        id=subscription.id,
        organization_id=subscription.organization_id,
        plan_id=subscription.plan_id,
        status=subscription.status,
        billing_cycle=subscription.billing_cycle,
        started_at=subscription.started_at,
        expires_at=subscription.expires_at,
        cancelled_at=subscription.cancelled_at,
        renewed_from=subscription.renewed_from,
        auto_renew=subscription.auto_renew,
        external_id=subscription.external_id,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        created_at=subscription.created_at,
        updated_at=subscription.updated_at,
        plan_name=plan.name if plan else None,
        plan_code=plan.code if plan else None,
        days_remaining=days_remaining,
        is_active=is_active,
    )


@router.post("/{subscription_id}/cancel", response_model=SubscriptionOut)
def cancel_subscription(
    subscription_id: UUID,
    request: SubscriptionCancelRequest,
    auth: AuthResult = Depends(require_billing_access),
    db: Session = Depends(get_db),
):
    """
    Cancela una suscripción.

    Requiere rol: owner o billing

    Opciones:
    - cancel_immediately=True: Cancela inmediatamente
    - cancel_immediately=False: Cancela al final del período actual
    """
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.id == subscription_id,
            Subscription.organization_id == auth.organization_id,
        )
        .first()
    )

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suscripción no encontrada",
        )

    if subscription.status == SubscriptionStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La suscripción ya está cancelada",
        )

    now = utcnow()
    subscription.cancelled_at = now
    subscription.auto_renew = False

    if request.cancel_immediately:
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.expires_at = now
    else:
        # Se mantiene activa hasta que expire
        subscription.status = SubscriptionStatus.CANCELLED

    db.commit()
    db.refresh(subscription)

    return subscription


@router.patch("/{subscription_id}/auto-renew", response_model=SubscriptionOut)
def toggle_auto_renew(
    subscription_id: UUID,
    auto_renew: bool = Query(..., description="Nuevo valor de auto-renovación"),
    auth: AuthResult = Depends(require_billing_access),
    db: Session = Depends(get_db),
):
    """
    Activa o desactiva la renovación automática de una suscripción.

    Requiere rol: owner o billing
    """
    subscription = (
        db.query(Subscription)
        .filter(
            Subscription.id == subscription_id,
            Subscription.organization_id == auth.organization_id,
        )
        .first()
    )

    if not subscription:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Suscripción no encontrada",
        )

    if subscription.status not in [
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.TRIAL.value,
    ]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Solo se puede modificar suscripciones activas",
        )

    subscription.auto_renew = auto_renew
    db.commit()
    db.refresh(subscription)

    return subscription
