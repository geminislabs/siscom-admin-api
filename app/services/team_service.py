"""
Servicio de lógica de negocio para Teams.

Maneja transacciones, validaciones de roles y reglas de visibilidad default.
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.team import Team, TeamMember, TeamVisibilityRule
from app.models.user import User
from app.schemas.team import (
    AccessMode,
    TeamCreate,
    TeamMemberCreate,
    TeamMemberUpdate,
    TeamRole,
    TeamStatus,
    TeamType,
    TeamUpdate,
    VisibilityRuleCreate,
    VisibilityRuleUpdate,
)
from app.utils.datetime import utcnow

ROLE_HIERARCHY = {
    TeamRole.OWNER: 100,
    TeamRole.ADMIN: 80,
    TeamRole.MEMBER: 60,
    TeamRole.EMPLOYEE: 60,
    TeamRole.DEPENDENT: 40,
    TeamRole.VIEWER: 30,
    TeamRole.EMERGENCY_CONTACT: 30,
    TeamRole.GUEST: 20,
}

ADMIN_OR_OWNER_ROLES = {TeamRole.OWNER, TeamRole.ADMIN}


def _get_role_level(role: TeamRole) -> int:
    return ROLE_HIERARCHY.get(role, 0)


def can_manage_team(role: TeamRole) -> bool:
    return role in ADMIN_OR_OWNER_ROLES


def can_invite_members(role: TeamRole) -> bool:
    return role in ADMIN_OR_OWNER_ROLES


def can_manage_visibility_rules(role: TeamRole) -> bool:
    return role in ADMIN_OR_OWNER_ROLES


def can_delete_team(role: TeamRole) -> bool:
    return role == TeamRole.OWNER


def get_user_permissions(role: TeamRole) -> dict[str, bool]:
    return {
        "can_manage_team": can_manage_team(role),
        "can_invite_members": can_invite_members(role),
        "can_manage_visibility_rules": can_manage_visibility_rules(role),
        "can_view_members": True,
        "can_delete_team": can_delete_team(role),
    }


def _get_default_visibility_rules(team_type: TeamType) -> list[dict]:
    """Retorna reglas de visibilidad default según el tipo de team."""
    if team_type == TeamType.FAMILY:
        return [
            {
                "subject_role": TeamRole.MEMBER.value,
                "viewer_role": TeamRole.OWNER.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
            {
                "subject_role": TeamRole.MEMBER.value,
                "viewer_role": TeamRole.ADMIN.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
            {
                "subject_role": TeamRole.DEPENDENT.value,
                "viewer_role": TeamRole.OWNER.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
            {
                "subject_role": TeamRole.DEPENDENT.value,
                "viewer_role": TeamRole.ADMIN.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
        ]
    elif team_type == TeamType.FRIENDS:
        return [
            {
                "subject_role": TeamRole.MEMBER.value,
                "viewer_role": TeamRole.OWNER.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
            {
                "subject_role": TeamRole.MEMBER.value,
                "viewer_role": TeamRole.ADMIN.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
        ]
    elif team_type == TeamType.WORKFORCE:
        return [
            {
                "subject_role": TeamRole.EMPLOYEE.value,
                "viewer_role": TeamRole.ADMIN.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
            {
                "subject_role": TeamRole.EMPLOYEE.value,
                "viewer_role": TeamRole.OWNER.value,
                "access_mode": AccessMode.ALWAYS.value,
            },
        ]
    elif team_type == TeamType.EMERGENCY:
        return [
            {
                "subject_role": TeamRole.MEMBER.value,
                "viewer_role": TeamRole.OWNER.value,
                "access_mode": AccessMode.EMERGENCY_ONLY.value,
            },
            {
                "subject_role": TeamRole.MEMBER.value,
                "viewer_role": TeamRole.EMERGENCY_CONTACT.value,
                "access_mode": AccessMode.EMERGENCY_ONLY.value,
            },
        ]
    return []


class TeamService:
    """Servicio para operaciones de Teams."""

    @staticmethod
    def create_team(
        db: Session,
        payload: TeamCreate,
        user: User,
        account_id: UUID,
    ) -> Team:
        """
        Crea un team con el usuario como OWNER y reglas de visibilidad default.
        Operación transaccional.
        """
        now = utcnow()
        team = Team(
            account_id=account_id,
            name=payload.name,
            type=payload.type.value,
            status=TeamStatus.ACTIVE.value,
            timezone=payload.timezone,
            expires_at=payload.expires_at,
            auto_delete_at=payload.auto_delete_at,
            team_metadata=payload.metadata,
            created_by_user_id=user.id,
            created_at=now,
            updated_at=now,
        )
        db.add(team)
        db.flush()

        owner_member = TeamMember(
            team_id=team.id,
            user_id=user.id,
            role=TeamRole.OWNER.value,
            joined_at=now,
            member_metadata={},
        )
        db.add(owner_member)

        default_rules = _get_default_visibility_rules(payload.type)
        for rule_data in default_rules:
            rule = TeamVisibilityRule(
                team_id=team.id,
                subject_role=rule_data["subject_role"],
                viewer_role=rule_data["viewer_role"],
                access_mode=rule_data["access_mode"],
                is_active=True,
                rule_metadata={},
                created_at=now,
                updated_at=now,
            )
            db.add(rule)

        db.commit()
        db.refresh(team)
        return team

    @staticmethod
    def get_team(db: Session, team_id: UUID) -> Optional[Team]:
        return db.query(Team).filter(Team.id == team_id).first()

    @staticmethod
    def get_team_or_404(db: Session, team_id: UUID) -> Team:
        team = TeamService.get_team(db, team_id)
        if not team:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Team no encontrado",
            )
        return team

    @staticmethod
    def get_user_membership(
        db: Session, team_id: UUID, user_id: UUID
    ) -> Optional[TeamMember]:
        return (
            db.query(TeamMember)
            .filter(TeamMember.team_id == team_id, TeamMember.user_id == user_id)
            .first()
        )

    @staticmethod
    def require_membership(db: Session, team_id: UUID, user_id: UUID) -> TeamMember:
        member = TeamService.get_user_membership(db, team_id, user_id)
        if not member:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No eres miembro de este team",
            )
        return member

    @staticmethod
    def require_role(
        db: Session, team_id: UUID, user_id: UUID, allowed_roles: set[TeamRole]
    ) -> TeamMember:
        member = TeamService.require_membership(db, team_id, user_id)
        if TeamRole(member.role) not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere uno de los siguientes roles: {', '.join(r.value for r in allowed_roles)}",
            )
        return member

    @staticmethod
    def list_user_teams(
        db: Session,
        user_id: UUID,
        status_filter: Optional[TeamStatus] = None,
        type_filter: Optional[TeamType] = None,
        include_deleted: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[tuple[Team, TeamMember, int]], int]:
        """Lista teams donde el usuario es miembro. Retorna (items, total)."""
        from sqlalchemy import func

        member_count_subq = (
            db.query(
                TeamMember.team_id,
                func.count(TeamMember.id).label("member_count"),
            )
            .group_by(TeamMember.team_id)
            .subquery()
        )

        query = (
            db.query(Team, TeamMember, member_count_subq.c.member_count)
            .join(TeamMember, Team.id == TeamMember.team_id)
            .outerjoin(member_count_subq, Team.id == member_count_subq.c.team_id)
            .filter(TeamMember.user_id == user_id)
        )

        if not include_deleted:
            query = query.filter(Team.status != TeamStatus.DELETED.value)

        if status_filter:
            query = query.filter(Team.status == status_filter.value)

        if type_filter:
            query = query.filter(Team.type == type_filter.value)

        total = query.count()
        offset = (page - 1) * page_size
        items = (
            query.order_by(Team.created_at.desc()).offset(offset).limit(page_size).all()
        )

        return items, total

    @staticmethod
    def update_team(
        db: Session,
        team: Team,
        payload: TeamUpdate,
    ) -> Team:
        if team.status == TeamStatus.DELETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede actualizar un team eliminado",
            )

        if payload.name is not None:
            team.name = payload.name
        if payload.timezone is not None:
            team.timezone = payload.timezone
        if payload.expires_at is not None:
            team.expires_at = payload.expires_at
        if payload.auto_delete_at is not None:
            team.auto_delete_at = payload.auto_delete_at
        if payload.metadata is not None:
            team.team_metadata = payload.metadata

        team.updated_at = utcnow()
        db.commit()
        db.refresh(team)
        return team

    @staticmethod
    def suspend_team(db: Session, team: Team) -> Team:
        if team.status != TeamStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se pueden suspender teams activos",
            )
        team.status = TeamStatus.SUSPENDED.value
        team.updated_at = utcnow()
        db.commit()
        db.refresh(team)
        return team

    @staticmethod
    def activate_team(
        db: Session, team: Team, new_expires_at: Optional[datetime] = None
    ) -> Team:
        if team.status == TeamStatus.DELETED.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede reactivar un team eliminado",
            )

        now = utcnow()
        if team.expires_at and team.expires_at <= now and new_expires_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El team ha expirado. Proporciona un nuevo expires_at",
            )

        if new_expires_at:
            team.expires_at = new_expires_at

        team.status = TeamStatus.ACTIVE.value
        team.updated_at = now
        db.commit()
        db.refresh(team)
        return team

    @staticmethod
    def expire_team(db: Session, team: Team) -> Team:
        now = utcnow()
        if team.status != TeamStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Solo se pueden expirar teams activos",
            )
        if team.expires_at is None or team.expires_at > now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El team aún no ha expirado",
            )
        team.status = TeamStatus.EXPIRED.value
        team.updated_at = now
        db.commit()
        db.refresh(team)
        return team

    @staticmethod
    def delete_team(db: Session, team: Team) -> None:
        team.status = TeamStatus.DELETED.value
        team.updated_at = utcnow()
        db.commit()

    @staticmethod
    def list_members(db: Session, team_id: UUID) -> list[TeamMember]:
        return (
            db.query(TeamMember)
            .filter(TeamMember.team_id == team_id)
            .order_by(TeamMember.joined_at)
            .all()
        )

    @staticmethod
    def add_member(
        db: Session,
        team: Team,
        payload: TeamMemberCreate,
        inviter: User,
        actor_role: TeamRole,
    ) -> TeamMember:
        if team.status != TeamStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se pueden agregar miembros a teams activos",
            )

        target_user = db.query(User).filter(User.id == payload.user_id).first()
        if not target_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado",
            )

        existing = TeamService.get_user_membership(db, team.id, payload.user_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="El usuario ya es miembro del team",
            )

        if payload.role == TeamRole.OWNER and actor_role != TeamRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un OWNER puede agregar otro OWNER",
            )

        member = TeamMember(
            team_id=team.id,
            user_id=payload.user_id,
            role=payload.role.value,
            invited_by_user_id=inviter.id,
            joined_at=utcnow(),
            member_metadata=payload.metadata,
        )
        db.add(member)
        db.commit()
        db.refresh(member)
        return member

    @staticmethod
    def update_member(
        db: Session,
        member: TeamMember,
        payload: TeamMemberUpdate,
        actor_role: TeamRole,
    ) -> TeamMember:
        target_role = TeamRole(member.role)

        if payload.role is not None and payload.role != target_role:
            if target_role == TeamRole.OWNER:
                owner_count = (
                    db.query(TeamMember)
                    .filter(
                        TeamMember.team_id == member.team_id,
                        TeamMember.role == TeamRole.OWNER.value,
                    )
                    .count()
                )
                if owner_count <= 1:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="No se puede degradar al último OWNER",
                    )

            if actor_role == TeamRole.ADMIN:
                if target_role == TeamRole.OWNER:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Un ADMIN no puede modificar a un OWNER",
                    )
                if payload.role == TeamRole.OWNER:
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail="Un ADMIN no puede promover a OWNER",
                    )

            member.role = payload.role.value

        if payload.metadata is not None:
            member.member_metadata = payload.metadata

        db.commit()
        db.refresh(member)
        return member

    @staticmethod
    def remove_member(
        db: Session, member: TeamMember, actor_id: UUID, actor_role: TeamRole
    ) -> None:
        target_role = TeamRole(member.role)

        if target_role == TeamRole.OWNER:
            owner_count = (
                db.query(TeamMember)
                .filter(
                    TeamMember.team_id == member.team_id,
                    TeamMember.role == TeamRole.OWNER.value,
                )
                .count()
            )
            if owner_count <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="No se puede remover al último OWNER",
                )

        is_self_removal = member.user_id == actor_id
        if not is_self_removal:
            if actor_role == TeamRole.ADMIN and target_role == TeamRole.OWNER:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Un ADMIN no puede remover a un OWNER",
                )

        db.delete(member)
        db.commit()

    @staticmethod
    def get_member_or_404(db: Session, team_id: UUID, member_id: UUID) -> TeamMember:
        member = (
            db.query(TeamMember)
            .filter(TeamMember.id == member_id, TeamMember.team_id == team_id)
            .first()
        )
        if not member:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Miembro no encontrado",
            )
        return member

    @staticmethod
    def list_visibility_rules(
        db: Session, team_id: UUID, active_only: bool = False
    ) -> list[TeamVisibilityRule]:
        query = db.query(TeamVisibilityRule).filter(
            TeamVisibilityRule.team_id == team_id
        )
        if active_only:
            query = query.filter(TeamVisibilityRule.is_active == True)  # noqa: E712
        return query.order_by(TeamVisibilityRule.created_at).all()

    @staticmethod
    def create_visibility_rule(
        db: Session, team: Team, payload: VisibilityRuleCreate
    ) -> TeamVisibilityRule:
        if team.status != TeamStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se pueden crear reglas en teams activos",
            )

        now = utcnow()
        schedule_dict = None
        if payload.schedule:
            schedule_dict = payload.schedule.model_dump()

        rule = TeamVisibilityRule(
            team_id=team.id,
            subject_role=payload.subject_role.value,
            viewer_role=payload.viewer_role.value,
            access_mode=payload.access_mode.value,
            schedule=schedule_dict,
            is_active=payload.is_active,
            rule_metadata=payload.metadata,
            created_at=now,
            updated_at=now,
        )
        db.add(rule)
        db.commit()
        db.refresh(rule)
        return rule

    @staticmethod
    def get_visibility_rule_or_404(
        db: Session, team_id: UUID, rule_id: UUID
    ) -> TeamVisibilityRule:
        rule = (
            db.query(TeamVisibilityRule)
            .filter(
                TeamVisibilityRule.id == rule_id,
                TeamVisibilityRule.team_id == team_id,
            )
            .first()
        )
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Regla de visibilidad no encontrada",
            )
        return rule

    @staticmethod
    def update_visibility_rule(
        db: Session,
        rule: TeamVisibilityRule,
        payload: VisibilityRuleUpdate,
    ) -> TeamVisibilityRule:
        from app.schemas.team import AccessMode

        if payload.subject_role is not None:
            rule.subject_role = payload.subject_role.value
        if payload.viewer_role is not None:
            rule.viewer_role = payload.viewer_role.value
        if payload.access_mode is not None:
            rule.access_mode = payload.access_mode.value
            if payload.access_mode == AccessMode.ALWAYS:
                rule.schedule = None
        if payload.schedule is not None:
            rule.schedule = payload.schedule.model_dump()
        elif payload.access_mode == AccessMode.ALWAYS:
            rule.schedule = None
        if payload.is_active is not None:
            rule.is_active = payload.is_active
        if payload.metadata is not None:
            rule.rule_metadata = payload.metadata

        effective_mode = AccessMode(rule.access_mode)
        if effective_mode == AccessMode.SCHEDULED and not rule.schedule:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="schedule es requerido cuando access_mode es SCHEDULED",
            )

        rule.updated_at = utcnow()
        db.commit()
        db.refresh(rule)
        return rule

    @staticmethod
    def set_visibility_rule_active(
        db: Session, rule: TeamVisibilityRule, is_active: bool
    ) -> TeamVisibilityRule:
        rule.is_active = is_active
        rule.updated_at = utcnow()
        db.commit()
        db.refresh(rule)
        return rule

    @staticmethod
    def delete_visibility_rule(db: Session, rule: TeamVisibilityRule) -> None:
        db.delete(rule)
        db.commit()
