"""
Endpoints públicos para invitaciones a Teams.

Implementa §7.4 y §7.5 de la spec.
"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full, get_team_rules_kafka_producer
from app.db.session import get_db
from app.models.user import User
from app.schemas.common import DataResponse
from app.schemas.team import InviteAcceptOut, InvitePublicOut, TeamRole, TeamType
from app.services.messaging.kafka_producer import TeamRulesKafkaProducer
from app.services.team_invite_service import TeamInviteService
from app.utils.datetime import utcnow

router = APIRouter()


def _publish_invite_event(
    producer: TeamRulesKafkaProducer,
    event_type: str,
    team_id: UUID,
    account_id: UUID,
    actor_user_id: UUID,
    payload: dict,
) -> None:
    event = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "team_id": str(team_id),
        "account_id": str(account_id),
        "actor_user_id": str(actor_user_id),
        "occurred_at": utcnow().isoformat() + "Z",
        "version": 1,
        "payload": payload,
    }
    producer.publish_team_event(event, team_id=str(team_id))


@router.get("/{token}", response_model=DataResponse[InvitePublicOut])
def get_invite_info(token: str, db: Session = Depends(get_db)):
    """Obtiene información pública de una invitación por token."""
    invite, team = TeamInviteService.get_public_invite_info(db, token)

    return DataResponse(
        data=InvitePublicOut(
            team_id=team.id,
            team_name=team.name,
            team_type=TeamType(team.type),
            invited_role=TeamRole(invite.invited_role),
            expires_at=invite.expires_at,
        )
    )


@router.post(
    "/{token}/accept",
    response_model=DataResponse[InviteAcceptOut],
    status_code=status.HTTP_201_CREATED,
)
def accept_invite(
    token: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Acepta una invitación y agrega al usuario como miembro del team."""
    member, team = TeamInviteService.accept_invite(db, token, current_user)

    _publish_invite_event(
        kafka_producer,
        "TEAM_MEMBER_JOINED",
        team.id,
        team.account_id,
        current_user.id,
        {
            "member_id": str(member.id),
            "user_id": str(current_user.id),
            "role": member.role,
            "via": "invite",
        },
    )

    return DataResponse(
        data=InviteAcceptOut(
            team_id=team.id,
            member_id=member.id,
            role=TeamRole(member.role),
        )
    )
