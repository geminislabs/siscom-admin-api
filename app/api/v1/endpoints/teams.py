"""
Endpoints para Teams y Members.

Implementa §4 (Teams) y §5 (Members) de la spec.
"""

from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user_full, get_team_rules_kafka_producer
from app.db.session import get_db
from app.models.team import Team, TeamInvite, TeamMember
from app.models.user import User
from app.schemas.common import DataResponse, PageMeta, PaginatedResponse
from app.schemas.team import (
    InviteMethod,
    MyPermissionsOut,
    TeamActivateRequest,
    TeamCreate,
    TeamInviteCreate,
    TeamInviteCreatedOut,
    TeamInviteOut,
    TeamInviteRevokeOut,
    TeamListItem,
    TeamMemberCreate,
    TeamMemberOut,
    TeamMemberUpdate,
    TeamOut,
    TeamRole,
    TeamStatus,
    TeamStatusOut,
    TeamType,
    TeamUpdate,
    VisibilityRuleCreate,
    VisibilityRuleOut,
    VisibilityRuleStatusOut,
    VisibilityRuleUpdate,
)
from app.services.messaging.kafka_producer import TeamRulesKafkaProducer
from app.services.team_invite_service import TeamInviteService, _build_invite_url
from app.services.team_service import (
    ADMIN_OR_OWNER_ROLES,
    TeamService,
    can_delete_team,
    can_manage_team,
    get_user_permissions,
)
from app.utils.datetime import utcnow

router = APIRouter()


def _build_team_out(team: Team) -> TeamOut:
    return TeamOut(
        id=team.id,
        account_id=team.account_id,
        name=team.name,
        type=TeamType(team.type),
        status=TeamStatus(team.status),
        timezone=team.timezone,
        expires_at=team.expires_at,
        auto_delete_at=team.auto_delete_at,
        metadata=team.team_metadata or {},
        created_by_user_id=team.created_by_user_id,
        created_at=team.created_at,
        updated_at=team.updated_at,
    )


def _build_team_list_item(
    team: Team, member: TeamMember, member_count: int
) -> TeamListItem:
    return TeamListItem(
        id=team.id,
        name=team.name,
        type=TeamType(team.type),
        status=TeamStatus(team.status),
        timezone=team.timezone,
        expires_at=team.expires_at,
        my_role=TeamRole(member.role),
        member_count=member_count or 1,
    )


def _build_member_out(member: TeamMember, user: Optional[User] = None) -> TeamMemberOut:
    display_name = None
    if user:
        display_name = user.full_name or user.email
    return TeamMemberOut(
        id=member.id,
        team_id=member.team_id,
        user_id=member.user_id,
        display_name=display_name,
        role=TeamRole(member.role),
        joined_at=member.joined_at,
        metadata=member.member_metadata or {},
    )


def _build_visibility_rule_out(rule) -> VisibilityRuleOut:
    return VisibilityRuleOut(
        id=rule.id,
        team_id=rule.team_id,
        subject_role=TeamRole(rule.subject_role),
        viewer_role=TeamRole(rule.viewer_role),
        access_mode=rule.access_mode,
        schedule=rule.schedule,
        is_active=rule.is_active,
        metadata=rule.rule_metadata or {},
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


def _build_invite_out(invite: TeamInvite) -> TeamInviteOut:
    return TeamInviteOut(
        id=invite.id,
        team_id=invite.team_id,
        invite_method=InviteMethod(invite.invite_method),
        invited_role=TeamRole(invite.invited_role),
        expires_at=invite.expires_at,
        max_uses=invite.max_uses,
        used_count=invite.used_count,
        is_active=invite.is_active,
        metadata=invite.invite_metadata or {},
        created_at=invite.created_at,
    )


def _build_invite_created_out(
    invite: TeamInvite, plain_token: str
) -> TeamInviteCreatedOut:
    base = _build_invite_out(invite)
    return TeamInviteCreatedOut(
        **base.model_dump(),
        token=plain_token,
        invite_url=_build_invite_url(plain_token),
    )


def _publish_team_event(
    producer: TeamRulesKafkaProducer,
    event_type: str,
    team: Team,
    actor_user_id: UUID,
    payload: Optional[dict] = None,
) -> None:
    event = {
        "event_id": str(uuid4()),
        "event_type": event_type,
        "team_id": str(team.id),
        "account_id": str(team.account_id),
        "actor_user_id": str(actor_user_id),
        "occurred_at": utcnow().isoformat() + "Z",
        "version": 1,
        "payload": payload or {},
    }
    producer.publish_team_event(event, team_id=str(team.id))


@router.post(
    "", response_model=DataResponse[TeamOut], status_code=status.HTTP_201_CREATED
)
def create_team(
    payload: TeamCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """
    Crea un team con el usuario actual como OWNER.
    Genera reglas de visibilidad default según el tipo.
    """
    from app.models.organization import Organization

    org = (
        db.query(Organization)
        .filter(Organization.id == current_user.organization_id)
        .first()
    )
    account_id = org.account_id if org else current_user.organization_id

    team = TeamService.create_team(db, payload, current_user, account_id)
    _publish_team_event(kafka_producer, "TEAM_CREATED", team, current_user.id)

    return DataResponse(data=_build_team_out(team))


@router.get("", response_model=PaginatedResponse[TeamListItem])
def list_teams(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    status_filter: Optional[TeamStatus] = Query(default=None, alias="status"),
    type_filter: Optional[TeamType] = Query(default=None, alias="type"),
    include_deleted: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
):
    """Lista teams donde el usuario es miembro."""
    items, total = TeamService.list_user_teams(
        db,
        user_id=current_user.id,
        status_filter=status_filter,
        type_filter=type_filter,
        include_deleted=include_deleted,
        page=page,
        page_size=page_size,
    )

    data = [
        _build_team_list_item(team, member, count or 1) for team, member, count in items
    ]

    return PaginatedResponse(
        data=data,
        meta=PageMeta(page=page, page_size=page_size, total=total),
    )


@router.get("/{team_id}", response_model=DataResponse[TeamOut])
def get_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Obtiene detalle de un team. Requiere ser miembro."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_membership(db, team_id, current_user.id)
    return DataResponse(data=_build_team_out(team))


@router.patch("/{team_id}", response_model=DataResponse[TeamOut])
def update_team(
    team_id: UUID,
    payload: TeamUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Actualiza un team. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    member = TeamService.require_role(
        db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES
    )

    if not can_manage_team(TeamRole(member.role)):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permisos para actualizar este team",
        )

    team = TeamService.update_team(db, team, payload)
    _publish_team_event(kafka_producer, "TEAM_UPDATED", team, current_user.id)

    return DataResponse(data=_build_team_out(team))


@router.post("/{team_id}/suspend", response_model=DataResponse[TeamStatusOut])
def suspend_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Suspende un team. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)

    team = TeamService.suspend_team(db, team)
    _publish_team_event(kafka_producer, "TEAM_SUSPENDED", team, current_user.id)

    return DataResponse(data=TeamStatusOut(id=team.id, status=TeamStatus(team.status)))


@router.post("/{team_id}/activate", response_model=DataResponse[TeamStatusOut])
def activate_team(
    team_id: UUID,
    payload: Optional[TeamActivateRequest] = None,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Reactiva un team suspendido o expirado. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)

    new_expires = payload.expires_at if payload else None
    team = TeamService.activate_team(db, team, new_expires)
    _publish_team_event(kafka_producer, "TEAM_ACTIVATED", team, current_user.id)

    return DataResponse(data=TeamStatusOut(id=team.id, status=TeamStatus(team.status)))


@router.post("/{team_id}/expire", response_model=DataResponse[TeamStatusOut])
def expire_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Marca un team como expirado. Solo si expires_at <= now()."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)

    team = TeamService.expire_team(db, team)
    _publish_team_event(kafka_producer, "TEAM_EXPIRED", team, current_user.id)

    return DataResponse(data=TeamStatusOut(id=team.id, status=TeamStatus(team.status)))


@router.delete("/{team_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_team(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Elimina un team lógicamente. Solo OWNER."""
    team = TeamService.get_team_or_404(db, team_id)
    member = TeamService.require_membership(db, team_id, current_user.id)

    if not can_delete_team(TeamRole(member.role)):
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo el OWNER puede eliminar el team",
        )

    _publish_team_event(kafka_producer, "TEAM_DELETED", team, current_user.id)
    TeamService.delete_team(db, team)

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{team_id}/members", response_model=DataResponse[list[TeamMemberOut]])
def list_members(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Lista miembros de un team. Requiere ser miembro."""
    TeamService.get_team_or_404(db, team_id)
    TeamService.require_membership(db, team_id, current_user.id)

    members = TeamService.list_members(db, team_id)

    user_ids = [m.user_id for m in members]
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    data = [_build_member_out(m, users.get(m.user_id)) for m in members]
    return DataResponse(data=data)


@router.post(
    "/{team_id}/members",
    response_model=DataResponse[TeamMemberOut],
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    team_id: UUID,
    payload: TeamMemberCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Agrega un miembro al team. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    actor = TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)

    member = TeamService.add_member(
        db, team, payload, current_user, TeamRole(actor.role)
    )

    target_user = db.query(User).filter(User.id == member.user_id).first()
    _publish_team_event(
        kafka_producer,
        "TEAM_MEMBER_ADDED",
        team,
        current_user.id,
        {
            "member_id": str(member.id),
            "user_id": str(member.user_id),
            "role": member.role,
        },
    )

    return DataResponse(data=_build_member_out(member, target_user))


@router.patch(
    "/{team_id}/members/{member_id}", response_model=DataResponse[TeamMemberOut]
)
def update_member(
    team_id: UUID,
    member_id: UUID,
    payload: TeamMemberUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Actualiza rol de un miembro. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    actor = TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)
    member = TeamService.get_member_or_404(db, team_id, member_id)

    member = TeamService.update_member(db, member, payload, TeamRole(actor.role))

    target_user = db.query(User).filter(User.id == member.user_id).first()
    _publish_team_event(
        kafka_producer,
        "TEAM_MEMBER_UPDATED",
        team,
        current_user.id,
        {"member_id": str(member.id), "role": member.role},
    )

    return DataResponse(data=_build_member_out(member, target_user))


@router.delete("/{team_id}/members/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_member(
    team_id: UUID,
    member_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Remueve un miembro del team."""
    team = TeamService.get_team_or_404(db, team_id)
    member = TeamService.get_member_or_404(db, team_id, member_id)

    is_self = member.user_id == current_user.id
    if not is_self:
        actor = TeamService.require_role(
            db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES
        )
        actor_role = TeamRole(actor.role)
    else:
        actor_membership = TeamService.get_user_membership(db, team_id, current_user.id)
        actor_role = (
            TeamRole(actor_membership.role) if actor_membership else TeamRole.MEMBER
        )

    user_id = member.user_id
    TeamService.remove_member(db, member, current_user.id, actor_role)

    _publish_team_event(
        kafka_producer,
        "TEAM_MEMBER_REMOVED",
        team,
        current_user.id,
        {"member_id": str(member_id), "user_id": str(user_id)},
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{team_id}/me", response_model=DataResponse[MyPermissionsOut])
def get_my_permissions(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Obtiene los permisos del usuario actual en un team."""
    TeamService.get_team_or_404(db, team_id)
    member = TeamService.require_membership(db, team_id, current_user.id)

    role = TeamRole(member.role)
    permissions = get_user_permissions(role)

    return DataResponse(
        data=MyPermissionsOut(
            team_id=team_id,
            user_id=current_user.id,
            role=role,
            permissions=permissions,
        )
    )


@router.get(
    "/{team_id}/visibility-rules", response_model=DataResponse[list[VisibilityRuleOut]]
)
def list_visibility_rules(
    team_id: UUID,
    active_only: bool = Query(default=False),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Lista reglas de visibilidad de un team."""
    TeamService.get_team_or_404(db, team_id)
    TeamService.require_membership(db, team_id, current_user.id)

    rules = TeamService.list_visibility_rules(db, team_id, active_only)
    data = [_build_visibility_rule_out(r) for r in rules]
    return DataResponse(data=data)


@router.post(
    "/{team_id}/visibility-rules",
    response_model=DataResponse[VisibilityRuleOut],
    status_code=status.HTTP_201_CREATED,
)
def create_visibility_rule(
    team_id: UUID,
    payload: VisibilityRuleCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Crea una regla de visibilidad. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)

    rule = TeamService.create_visibility_rule(db, team, payload)

    _publish_team_event(
        kafka_producer,
        "VISIBILITY_RULE_CREATED",
        team,
        current_user.id,
        {
            "rule_id": str(rule.id),
            "subject_role": rule.subject_role,
            "viewer_role": rule.viewer_role,
            "access_mode": rule.access_mode,
        },
    )

    return DataResponse(data=_build_visibility_rule_out(rule))


@router.patch(
    "/{team_id}/visibility-rules/{rule_id}",
    response_model=DataResponse[VisibilityRuleOut],
)
def update_visibility_rule(
    team_id: UUID,
    rule_id: UUID,
    payload: VisibilityRuleUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Actualiza una regla de visibilidad. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)
    rule = TeamService.get_visibility_rule_or_404(db, team_id, rule_id)

    rule = TeamService.update_visibility_rule(db, rule, payload)

    _publish_team_event(
        kafka_producer,
        "VISIBILITY_RULE_UPDATED",
        team,
        current_user.id,
        {"rule_id": str(rule.id)},
    )

    return DataResponse(data=_build_visibility_rule_out(rule))


@router.post(
    "/{team_id}/visibility-rules/{rule_id}/activate",
    response_model=DataResponse[VisibilityRuleStatusOut],
)
def activate_visibility_rule(
    team_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Activa una regla de visibilidad."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)
    rule = TeamService.get_visibility_rule_or_404(db, team_id, rule_id)

    rule = TeamService.set_visibility_rule_active(db, rule, True)

    _publish_team_event(
        kafka_producer,
        "VISIBILITY_RULE_UPDATED",
        team,
        current_user.id,
        {"rule_id": str(rule.id), "is_active": True},
    )

    return DataResponse(data=VisibilityRuleStatusOut(id=rule.id, is_active=True))


@router.post(
    "/{team_id}/visibility-rules/{rule_id}/deactivate",
    response_model=DataResponse[VisibilityRuleStatusOut],
)
def deactivate_visibility_rule(
    team_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Desactiva una regla de visibilidad."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)
    rule = TeamService.get_visibility_rule_or_404(db, team_id, rule_id)

    rule = TeamService.set_visibility_rule_active(db, rule, False)

    _publish_team_event(
        kafka_producer,
        "VISIBILITY_RULE_UPDATED",
        team,
        current_user.id,
        {"rule_id": str(rule.id), "is_active": False},
    )

    return DataResponse(data=VisibilityRuleStatusOut(id=rule.id, is_active=False))


@router.delete(
    "/{team_id}/visibility-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_visibility_rule(
    team_id: UUID,
    rule_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Elimina una regla de visibilidad."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)
    rule = TeamService.get_visibility_rule_or_404(db, team_id, rule_id)

    rule_id_str = str(rule.id)
    TeamService.delete_visibility_rule(db, rule)

    _publish_team_event(
        kafka_producer,
        "VISIBILITY_RULE_DELETED",
        team,
        current_user.id,
        {"rule_id": rule_id_str},
    )

    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{team_id}/invites",
    response_model=DataResponse[TeamInviteCreatedOut],
    status_code=status.HTTP_201_CREATED,
)
def create_invite(
    team_id: UUID,
    payload: TeamInviteCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Crea una invitación al team. Requiere OWNER o ADMIN."""
    team = TeamService.get_team_or_404(db, team_id)
    actor = TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)

    invite, plain_token = TeamInviteService.create_invite(
        db, team, payload, current_user, TeamRole(actor.role)
    )

    _publish_team_event(
        kafka_producer,
        "TEAM_INVITE_CREATED",
        team,
        current_user.id,
        {"invite_id": str(invite.id), "invited_role": invite.invited_role},
    )

    return DataResponse(data=_build_invite_created_out(invite, plain_token))


@router.get("/{team_id}/invites", response_model=DataResponse[list[TeamInviteOut]])
def list_invites(
    team_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """Lista invitaciones de un team. Requiere OWNER o ADMIN."""
    TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)

    invites = TeamInviteService.list_invites(db, team_id)
    return DataResponse(data=[_build_invite_out(i) for i in invites])


@router.post(
    "/{team_id}/invites/{invite_id}/revoke",
    response_model=DataResponse[TeamInviteRevokeOut],
)
def revoke_invite(
    team_id: UUID,
    invite_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    kafka_producer: TeamRulesKafkaProducer = Depends(get_team_rules_kafka_producer),
):
    """Revoca una invitación."""
    team = TeamService.get_team_or_404(db, team_id)
    TeamService.require_role(db, team_id, current_user.id, ADMIN_OR_OWNER_ROLES)
    invite = TeamInviteService.get_invite_or_404(db, team_id, invite_id)

    invite = TeamInviteService.revoke_invite(db, invite)

    _publish_team_event(
        kafka_producer,
        "TEAM_INVITE_REVOKED",
        team,
        current_user.id,
        {"invite_id": str(invite.id)},
    )

    return DataResponse(data=TeamInviteRevokeOut(id=invite.id, is_active=False))
