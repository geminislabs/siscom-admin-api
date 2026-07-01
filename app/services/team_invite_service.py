"""
Servicio de lógica de negocio para invitaciones a Teams.
"""

import hashlib
import secrets
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.team import Team, TeamInvite, TeamMember
from app.models.user import User
from app.schemas.team import TeamInviteCreate, TeamRole, TeamStatus
from app.services.team_service import TeamService
from app.utils.datetime import utcnow


def _hash_token(plain_token: str) -> str:
    return hashlib.sha256(plain_token.encode()).hexdigest()


def _generate_invite_token() -> tuple[str, str]:
    plain = secrets.token_urlsafe(32)
    return plain, _hash_token(plain)


def _build_invite_url(plain_token: str) -> str:
    base = settings.FRONTEND_URL.rstrip("/")
    return f"{base}/invite/{plain_token}"


class TeamInviteService:
    """Servicio para operaciones de invitaciones."""

    @staticmethod
    def create_invite(
        db: Session,
        team: Team,
        payload: TeamInviteCreate,
        creator: User,
        actor_role: TeamRole,
    ) -> tuple[TeamInvite, str]:
        if team.status != TeamStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Solo se pueden crear invitaciones en teams activos",
            )

        if payload.invited_role == TeamRole.OWNER and actor_role != TeamRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Solo un OWNER puede invitar con rol OWNER",
            )

        plain_token, token_hash = _generate_invite_token()
        invite = TeamInvite(
            team_id=team.id,
            created_by_user_id=creator.id,
            invite_method=payload.invite_method.value,
            invited_role=payload.invited_role.value,
            token_hash=token_hash,
            expires_at=payload.expires_at,
            max_uses=payload.max_uses,
            used_count=0,
            is_active=True,
            invite_metadata=payload.metadata,
            created_at=utcnow(),
        )
        db.add(invite)
        db.commit()
        db.refresh(invite)
        return invite, plain_token

    @staticmethod
    def list_invites(db: Session, team_id: UUID) -> list[TeamInvite]:
        return (
            db.query(TeamInvite)
            .filter(TeamInvite.team_id == team_id)
            .order_by(TeamInvite.created_at.desc())
            .all()
        )

    @staticmethod
    def get_invite_or_404(db: Session, team_id: UUID, invite_id: UUID) -> TeamInvite:
        invite = (
            db.query(TeamInvite)
            .filter(TeamInvite.id == invite_id, TeamInvite.team_id == team_id)
            .first()
        )
        if not invite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Invitación no encontrada",
            )
        return invite

    @staticmethod
    def revoke_invite(db: Session, invite: TeamInvite) -> TeamInvite:
        invite.is_active = False
        db.commit()
        db.refresh(invite)
        return invite

    @staticmethod
    def _find_valid_invite_by_token(db: Session, plain_token: str) -> TeamInvite:
        token_hash = _hash_token(plain_token)
        invite = (
            db.query(TeamInvite).filter(TeamInvite.token_hash == token_hash).first()
        )
        if not invite:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="INVITE_NOT_FOUND",
            )

        now = utcnow()
        if not invite.is_active:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="INVITE_ALREADY_USED",
            )
        # Convertir a naive UTC si tiene timezone antes de comparar
        expires_at_naive = (
            invite.expires_at.replace(tzinfo=None)
            if invite.expires_at.tzinfo
            else invite.expires_at
        )
        if expires_at_naive <= now:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="INVITE_EXPIRED",
            )
        if invite.used_count >= invite.max_uses:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="INVITE_ALREADY_USED",
            )

        team = db.query(Team).filter(Team.id == invite.team_id).first()
        if not team or team.status != TeamStatus.ACTIVE.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El team no está activo",
            )

        return invite

    @staticmethod
    def get_public_invite_info(
        db: Session, plain_token: str
    ) -> tuple[TeamInvite, Team]:
        invite = TeamInviteService._find_valid_invite_by_token(db, plain_token)
        team = TeamService.get_team_or_404(db, invite.team_id)
        return invite, team

    @staticmethod
    def accept_invite(
        db: Session, plain_token: str, user: User
    ) -> tuple[TeamMember, Team]:
        invite = TeamInviteService._find_valid_invite_by_token(db, plain_token)
        team = TeamService.get_team_or_404(db, invite.team_id)

        existing = TeamService.get_user_membership(db, team.id, user.id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="ALREADY_MEMBER",
            )

        now = utcnow()
        member = TeamMember(
            team_id=team.id,
            user_id=user.id,
            role=invite.invited_role,
            invited_by_user_id=invite.created_by_user_id,
            joined_at=now,
            member_metadata={},
        )
        db.add(member)

        invite.used_count += 1
        if invite.used_count >= invite.max_uses:
            invite.is_active = False

        db.commit()
        db.refresh(member)
        db.refresh(team)
        return member, team
