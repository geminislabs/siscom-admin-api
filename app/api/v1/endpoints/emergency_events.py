"""Endpoints para Emergency Events."""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full, get_db, get_team_rules_kafka_producer
from app.models.user import User
from app.schemas.common import DataResponse, PageMeta, PaginatedResponse
from app.schemas.emergency_event import EmergencyEventCreate, EmergencyEventOut
from app.schemas.team import TeamRole
from app.services.emergency_event_service import EmergencyEventService
from app.services.messaging.kafka_producer import TeamRulesKafkaProducer
from app.services.team_service import TeamService

router = APIRouter()


def _build_emergency_event_out(event) -> EmergencyEventOut:
    """Helper para construir EmergencyEventOut desde modelo."""
    return EmergencyEventOut(
        id=event.id,
        team_id=event.team_id,
        triggered_by_user_id=event.triggered_by_user_id,
        emergency_type=event.emergency_type,
        status=event.status,
        started_at=event.started_at,
        ended_at=event.ended_at,
        metadata=event.event_metadata,
    )


@router.post(
    "/{team_id}/emergency-events",
    response_model=DataResponse[EmergencyEventOut],
    status_code=status.HTTP_201_CREATED,
)
def create_emergency_event(
    team_id: UUID,
    payload: EmergencyEventCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """
    Crea un evento de emergencia en un team.
    El usuario debe ser miembro del team.
    """
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_membership(db, team.id, current_user.id)
    event = EmergencyEventService.create_event(db, team, payload, current_user)

    # Publicar evento Kafka
    kafka_producer.publish_team_event(
        {
            "event_type": "EMERGENCY_STARTED",
            "team_id": str(team.id),
            "emergency_event_id": str(event.id),
            "triggered_by_user_id": str(current_user.id),
            "emergency_type": event.emergency_type,
            "started_at": event.started_at.isoformat(),
        },
        team_id=str(team.id),
    )

    return DataResponse(data=_build_emergency_event_out(event))


@router.get(
    "/{team_id}/emergency-events",
    response_model=PaginatedResponse[EmergencyEventOut],
)
def list_emergency_events(
    team_id: UUID,
    status_filter: Optional[str] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Lista eventos de emergencia de un team.
    El usuario debe ser miembro del team.
    """
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_membership(db, team.id, current_user.id)
    events, total = EmergencyEventService.list_events(
        db, team.id, status_filter, page, page_size
    )

    return PaginatedResponse(
        data=[_build_emergency_event_out(e) for e in events],
        meta=PageMeta(page=page, page_size=page_size, total=total),
    )


@router.post(
    "/{team_id}/emergency-events/{event_id}/resolve",
    response_model=DataResponse[EmergencyEventOut],
)
def resolve_emergency_event(
    team_id: UUID,
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """
    Resuelve un evento de emergencia.
    Permisos: Usuario que lo activó, OWNER o ADMIN.
    """
    team = TeamService.get_team_or_404(db, team_id)
    membership = TeamService.require_membership(db, team.id, current_user.id)
    event = EmergencyEventService.get_event_by_id(db, event_id, team.id)
    event = EmergencyEventService.resolve_event(
        db, event, current_user, TeamRole(membership.role)
    )

    # Publicar evento Kafka
    kafka_producer.publish_team_event(
        {
            "event_type": "EMERGENCY_RESOLVED",
            "team_id": str(team.id),
            "emergency_event_id": str(event.id),
            "resolved_by_user_id": str(current_user.id),
            "ended_at": event.ended_at.isoformat() if event.ended_at else None,
        },
        team_id=str(team.id),
    )

    return DataResponse(data=_build_emergency_event_out(event))


@router.post(
    "/{team_id}/emergency-events/{event_id}/cancel",
    response_model=DataResponse[EmergencyEventOut],
)
def cancel_emergency_event(
    team_id: UUID,
    event_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """
    Cancela un evento de emergencia.
    Permisos: Usuario que lo activó, OWNER o ADMIN.
    """
    team = TeamService.get_team_or_404(db, team_id)
    membership = TeamService.require_membership(db, team.id, current_user.id)
    event = EmergencyEventService.get_event_by_id(db, event_id, team.id)
    event = EmergencyEventService.cancel_event(
        db, event, current_user, TeamRole(membership.role)
    )

    # Publicar evento Kafka
    kafka_producer.publish_team_event(
        {
            "event_type": "EMERGENCY_CANCELLED",
            "team_id": str(team.id),
            "emergency_event_id": str(event.id),
            "cancelled_by_user_id": str(current_user.id),
            "ended_at": event.ended_at.isoformat() if event.ended_at else None,
        },
        team_id=str(team.id),
    )

    return DataResponse(data=_build_emergency_event_out(event))
