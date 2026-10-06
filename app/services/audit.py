"""
Servicio de Auditoría.

Centraliza el registro de eventos de auditoría en la tabla account_events.

USO:
    from app.services.audit import AuditService

    # Registrar evento de usuario agregado a organización
    AuditService.log_org_user_added(
        db=db,
        account_id=account_id,
        organization_id=organization_id,
        actor_user_id=current_user_id,
        target_user_id=new_user_id,
        role="member",
    )
"""

import logging
from typing import Any, Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.account_event import (
    AccountEvent,
    ActorType,
    EventType,
    TargetType,
)

logger = logging.getLogger(__name__)


class AuditService:
    """
    Servicio centralizado para registro de eventos de auditoría.

    Todos los métodos son estáticos para facilitar el uso.
    Los eventos se registran de forma síncrona en la misma transacción.
    """

    @staticmethod
    def log_event(
        db: Session,
        account_id: UUID,
        event_type: str,
        target_type: str,
        *,
        organization_id: Optional[UUID] = None,
        actor_user_id: Optional[UUID] = None,
        actor_type: str = ActorType.USER.value,
        target_id: Optional[UUID] = None,
        metadata: Optional[dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        auto_commit: bool = False,
    ) -> AccountEvent:
        """
        Registra un evento de auditoría.

        Args:
            db: Sesión de base de datos
            account_id: ID de la cuenta
            event_type: Tipo de evento
            target_type: Tipo de entidad afectada
            organization_id: ID de la organización (opcional)
            actor_user_id: ID del usuario que realizó la acción
            actor_type: Tipo de actor (user, system, service, api)
            target_id: ID de la entidad afectada
            metadata: Información adicional del evento
            ip_address: IP del actor
            user_agent: User agent del actor
            auto_commit: Si debe hacer commit automático

        Returns:
            AccountEvent creado
        """
        event = AccountEvent(
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            actor_type=actor_type,
            event_type=event_type,
            target_type=target_type,
            target_id=target_id,
            event_metadata=metadata,
            ip_address=ip_address,
            user_agent=user_agent,
        )

        db.add(event)

        if auto_commit:
            db.commit()
            db.refresh(event)

        logger.debug(
            f"[AUDIT] {event_type} | account={account_id} | "
            f"org={organization_id} | actor={actor_user_id} | "
            f"target={target_type}:{target_id}"
        )

        return event

    # =========================================================================
    # Organization Users Events
    # =========================================================================

    @staticmethod
    def log_org_user_added(
        db: Session,
        account_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        target_user_id: UUID,
        role: str,
        **kwargs: Any,
    ) -> AccountEvent:
        """Registra cuando se agrega un usuario a una organización."""
        return AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EventType.ORG_USER_ADDED.value,
            target_type=TargetType.ORGANIZATION_USER.value,
            target_id=target_user_id,
            metadata={
                "user_id": str(target_user_id),
                "role": role,
            },
            **kwargs,
        )

    @staticmethod
    def log_org_user_removed(
        db: Session,
        account_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        target_user_id: UUID,
        previous_role: str,
        default_organization_reassigned_to: Optional[UUID] = None,
        **kwargs: Any,
    ) -> AccountEvent:
        """Registra cuando se elimina un usuario de una organización.

        `default_organization_reassigned_to` va sólo si la que se quitó era su
        organización por defecto y ésta pasó a otra (ver
        `OrganizationService.reparar_organizacion_por_defecto`).
        """
        metadata = {
            "user_id": str(target_user_id),
            "previous_role": previous_role,
        }
        if default_organization_reassigned_to is not None:
            metadata["default_organization_reassigned_to"] = str(
                default_organization_reassigned_to
            )
        return AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EventType.ORG_USER_REMOVED.value,
            target_type=TargetType.ORGANIZATION_USER.value,
            target_id=target_user_id,
            metadata=metadata,
            **kwargs,
        )

    @staticmethod
    def log_org_user_role_changed(
        db: Session,
        account_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        target_user_id: UUID,
        old_role: str,
        new_role: str,
        **kwargs: Any,
    ) -> AccountEvent:
        """Registra cuando se cambia el rol de un usuario en una organización."""
        return AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EventType.ORG_USER_ROLE_CHANGED.value,
            target_type=TargetType.ORGANIZATION_USER.value,
            target_id=target_user_id,
            metadata={
                "user_id": str(target_user_id),
                "old_role": old_role,
                "new_role": new_role,
            },
            **kwargs,
        )

    @staticmethod
    def log_org_user_status_changed(
        db: Session,
        account_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        target_user_id: UUID,
        old_status: str,
        new_status: str,
        default_organization_reassigned_to: Optional[UUID] = None,
        **kwargs: Any,
    ) -> AccountEvent:
        """Registra cuando se pausa o reactiva una membresía (no la cuenta).

        `default_organization_reassigned_to` va sólo si la pausa movió la
        organización por defecto a otra membresía activa.
        """
        metadata = {
            "user_id": str(target_user_id),
            "old_status": old_status,
            "new_status": new_status,
        }
        if default_organization_reassigned_to is not None:
            metadata["default_organization_reassigned_to"] = str(
                default_organization_reassigned_to
            )
        return AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EventType.ORG_USER_STATUS_CHANGED.value,
            target_type=TargetType.ORGANIZATION_USER.value,
            target_id=target_user_id,
            metadata=metadata,
            **kwargs,
        )

    # =========================================================================
    # Organization Capabilities Events
    # =========================================================================

    @staticmethod
    def log_org_capability_created(
        db: Session,
        account_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        capability_id: UUID,
        capability_code: str,
        value: Any,
        reason: Optional[str] = None,
        **kwargs: Any,
    ) -> AccountEvent:
        """Registra cuando se crea un override de capability."""
        return AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EventType.ORG_CAPABILITY_CREATED.value,
            target_type=TargetType.ORGANIZATION_CAPABILITY.value,
            target_id=capability_id,
            metadata={
                "capability_code": capability_code,
                "value": str(value) if value is not None else None,
                "reason": reason,
            },
            **kwargs,
        )

    @staticmethod
    def log_org_capability_updated(
        db: Session,
        account_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        capability_id: UUID,
        capability_code: str,
        old_value: Any,
        new_value: Any,
        reason: Optional[str] = None,
        **kwargs: Any,
    ) -> AccountEvent:
        """Registra cuando se actualiza un override de capability."""
        return AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EventType.ORG_CAPABILITY_UPDATED.value,
            target_type=TargetType.ORGANIZATION_CAPABILITY.value,
            target_id=capability_id,
            metadata={
                "capability_code": capability_code,
                "old_value": str(old_value) if old_value is not None else None,
                "new_value": str(new_value) if new_value is not None else None,
                "reason": reason,
            },
            **kwargs,
        )

    @staticmethod
    def log_org_capability_deleted(
        db: Session,
        account_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        capability_id: UUID,
        capability_code: str,
        previous_value: Any,
        **kwargs: Any,
    ) -> AccountEvent:
        """Registra cuando se elimina un override de capability."""
        return AuditService.log_event(
            db=db,
            account_id=account_id,
            organization_id=organization_id,
            actor_user_id=actor_user_id,
            event_type=EventType.ORG_CAPABILITY_DELETED.value,
            target_type=TargetType.ORGANIZATION_CAPABILITY.value,
            target_id=capability_id,
            metadata={
                "capability_code": capability_code,
                "previous_value": (
                    str(previous_value) if previous_value is not None else None
                ),
            },
            **kwargs,
        )
