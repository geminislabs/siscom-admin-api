"""Servicio para operaciones de Emergency Events."""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.team import EmergencyEvent, Team, TeamMember
from app.models.user import User
from app.schemas.emergency_event import EmergencyEventCreate
from app.schemas.team import TeamRole
from app.utils.datetime import utcnow


class EmergencyEventService:
    @staticmethod
    def get_event_by_id(db: Session, event_id: UUID, team_id: UUID) -> EmergencyEvent:
        """Obtiene un evento de emergencia por ID y team_id."""
        event = (
            db.query(EmergencyEvent)
            .filter(EmergencyEvent.id == event_id, EmergencyEvent.team_id == team_id)
            .first()
        )
        if not event:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Evento de emergencia no encontrado",
            )
        return event

    @staticmethod
    def create_event(
        db: Session,
        team: Team,
        payload: EmergencyEventCreate,
        user: User,
    ) -> EmergencyEvent:
        """
        Crea un evento de emergencia.
        Validaciones:
        - Team debe estar ACTIVE
        - Usuario debe ser miembro del team
        - Evitar múltiples eventos ACTIVE del mismo usuario en el mismo team
        """
        # Validar que team esté activo
        if team.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El team no está activo",
            )

        # Validar que usuario sea miembro
        membership = (
            db.query(TeamMember)
            .filter(TeamMember.team_id == team.id, TeamMember.user_id == user.id)
            .first()
        )
        if not membership:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Usuario no es miembro del team",
            )

        # Validar que no tenga eventos ACTIVE previos (recomendación)
        existing_active = (
            db.query(EmergencyEvent)
            .filter(
                EmergencyEvent.team_id == team.id,
                EmergencyEvent.triggered_by_user_id == user.id,
                EmergencyEvent.status == "ACTIVE",
            )
            .first()
        )
        if existing_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Usuario ya tiene un evento de emergencia activo en este team",
            )

        # Crear evento
        event = EmergencyEvent(
            team_id=team.id,
            triggered_by_user_id=user.id,
            emergency_type=payload.emergency_type.value,
            status="ACTIVE",
            started_at=utcnow(),
            event_metadata=payload.metadata,
        )
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    @staticmethod
    def list_events(
        db: Session,
        team_id: UUID,
        status_filter: Optional[str] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[EmergencyEvent], int]:
        """
        Lista eventos de emergencia de un team.
        Retorna (eventos, total_count).
        """
        query = db.query(EmergencyEvent).filter(EmergencyEvent.team_id == team_id)

        if status_filter:
            query = query.filter(EmergencyEvent.status == status_filter)

        # Total count
        total = query.count()

        # Paginación
        offset = (page - 1) * page_size
        events = (
            query.order_by(EmergencyEvent.started_at.desc())
            .offset(offset)
            .limit(page_size)
            .all()
        )

        return events, total

    @staticmethod
    def resolve_event(
        db: Session,
        event: EmergencyEvent,
        user: User,
        actor_role: TeamRole,
    ) -> EmergencyEvent:
        """
        Resuelve un evento de emergencia.
        Permisos: Usuario que lo activó, OWNER o ADMIN.
        """
        # Validar que esté ACTIVE
        if event.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El evento no está activo",
            )

        # Validar permisos: creator o OWNER/ADMIN
        if event.triggered_by_user_id != user.id and actor_role not in (
            TeamRole.OWNER,
            TeamRole.ADMIN,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sin permisos para resolver este evento",
            )

        # Resolver evento
        event.status = "RESOLVED"
        event.ended_at = utcnow()
        db.add(event)
        db.commit()
        db.refresh(event)
        return event

    @staticmethod
    def cancel_event(
        db: Session,
        event: EmergencyEvent,
        user: User,
        actor_role: TeamRole,
    ) -> EmergencyEvent:
        """
        Cancela un evento de emergencia.
        Permisos: Usuario que lo activó, OWNER o ADMIN.
        """
        # Validar que esté ACTIVE
        if event.status != "ACTIVE":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El evento no está activo",
            )

        # Validar permisos: creator o OWNER/ADMIN
        if event.triggered_by_user_id != user.id and actor_role not in (
            TeamRole.OWNER,
            TeamRole.ADMIN,
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Sin permisos para cancelar este evento",
            )

        # Cancelar evento
        event.status = "CANCELLED"
        event.ended_at = utcnow()
        db.add(event)
        db.commit()
        db.refresh(event)
        return event
