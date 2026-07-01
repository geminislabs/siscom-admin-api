"""Endpoints internos para sincronización de teams."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full, get_db
from app.models.team import EmergencyEvent, Team, TeamMember, TeamVisibilityRule
from app.models.user import User
from app.schemas.common import DataResponse
from app.services.team_service import TeamService

router = APIRouter()


def _build_team_snapshot(db: Session, team: Team) -> dict[str, Any]:
    """
    Construye un snapshot completo de un team para sincronización.
    Incluye: team, members, visibility_rules, active_emergency_events.
    """
    # Obtener miembros
    members = db.query(TeamMember).filter(TeamMember.team_id == team.id).all()

    # Obtener reglas de visibilidad activas
    visibility_rules = (
        db.query(TeamVisibilityRule)
        .filter(
            TeamVisibilityRule.team_id == team.id,
            TeamVisibilityRule.is_active.is_(True),
        )
        .all()
    )

    # Obtener eventos de emergencia activos
    active_emergency_events = (
        db.query(EmergencyEvent)
        .filter(EmergencyEvent.team_id == team.id, EmergencyEvent.status == "ACTIVE")
        .all()
    )

    return {
        "team": {
            "id": str(team.id),
            "account_id": str(team.account_id),
            "name": team.name,
            "type": team.type,
            "status": team.status,
            "timezone": team.timezone,
            "expires_at": team.expires_at.isoformat() if team.expires_at else None,
            "auto_delete_at": (
                team.auto_delete_at.isoformat() if team.auto_delete_at else None
            ),
            "metadata": team.team_metadata,
            "created_by_user_id": str(team.created_by_user_id),
            "created_at": team.created_at.isoformat() if team.created_at else None,
            "updated_at": team.updated_at.isoformat() if team.updated_at else None,
        },
        "members": [
            {
                "id": str(m.id),
                "team_id": str(m.team_id),
                "user_id": str(m.user_id),
                "role": m.role,
                "joined_at": m.joined_at.isoformat() if m.joined_at else None,
            }
            for m in members
        ],
        "visibility_rules": [
            {
                "id": str(r.id),
                "team_id": str(r.team_id),
                "subject_role": r.subject_role,
                "viewer_role": r.viewer_role,
                "access_mode": r.access_mode,
                "schedule": r.schedule,
                "is_active": r.is_active,
            }
            for r in visibility_rules
        ],
        "active_emergency_events": [
            {
                "id": str(e.id),
                "team_id": str(e.team_id),
                "triggered_by_user_id": str(e.triggered_by_user_id),
                "emergency_type": e.emergency_type,
                "status": e.status,
                "started_at": e.started_at.isoformat() if e.started_at else None,
                "metadata": e.event_metadata,
            }
            for e in active_emergency_events
        ],
    }


@router.get("/internal/teams/{team_id}/snapshot")
def get_team_snapshot(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Obtiene un snapshot completo de un team para sincronización.
    Uso: permite que team-realtime-api cargue estado inicial.
    """
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_membership(db, team.id, current_user.id)
    snapshot = _build_team_snapshot(db, team)
    return DataResponse(data=snapshot)


@router.get("/internal/teams/snapshot")
def get_teams_snapshot(
    updated_after: Optional[datetime] = Query(None),
    account_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Obtiene snapshots de múltiples teams para sincronización.
    Uso: carga inicial o recuperación de caché.

    Query params:
    - updated_after: traer cambios desde fecha
    - account_id: filtrar por account
    """
    query = db.query(Team).filter(Team.status == "ACTIVE")

    if account_id:
        query = query.filter(Team.account_id == account_id)
    elif hasattr(current_user, "account_id") and current_user.account_id:
        # Si no se especifica account_id, usar el del usuario actual si existe
        query = query.filter(Team.account_id == current_user.account_id)

    if updated_after:
        query = query.filter(Team.updated_at >= updated_after)

    teams = query.all()
    snapshots = [_build_team_snapshot(db, team) for team in teams]

    return DataResponse(data=snapshots)
