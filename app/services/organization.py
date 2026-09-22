"""
Servicio de Gestión de Organizaciones y Roles.

Este módulo centraliza la lógica de:
- Resolución de roles organizacionales
- Verificación de permisos
- Gestión de membresías

MODELO CONCEPTUAL:
==================
Account = Raíz comercial (billing, facturación)
Organization = Raíz operativa (permisos, uso diario)

Las suscripciones, dispositivos, usuarios pertenecen a Organization.
Los pagos pertenecen a Account.

USO:
    from app.services.organization import OrganizationService
    # Verificar si puede gestionar usuarios
    if not OrganizationService.can_manage_users(db, user_id, org_id):
        raise HTTPException(403, "Sin permisos")
    # Obtener rol del usuario
    role = OrganizationService.get_user_role(db, user_id, org_id)
"""

from typing import Optional
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.subscription import Subscription
from app.models.user import User
from app.services.subscription_query import (
    get_active_subscriptions as _get_active_subscriptions,
)
from app.services.subscription_query import (
    get_subscription_history as _get_subscription_history,
)


class OrganizationService:
    """
    Servicio centralizado para gestión de organizaciones.
    """

    @staticmethod
    def get_user_role(
        db: Session,
        user_id: UUID,
        organization_id: UUID,
    ) -> Optional[OrganizationRole]:
        """
        Obtiene el rol de un usuario en una organización.

        Args:
            db: Sesión de base de datos
            user_id: ID del usuario
            organization_id: ID de la organización

        Returns:
            OrganizationRole o None si no es miembro
        """
        membership = (
            db.query(OrganizationUser)
            .filter(
                OrganizationUser.user_id == user_id,
                OrganizationUser.organization_id == organization_id,
            )
            .first()
        )

        if membership:
            return OrganizationRole(membership.role)

        # Aquí había un *fallback* heredado: sin membresía, si
        # `user.organization_id` coincidía y `user.is_master` era cierto,
        # devolvía OWNER. Se borró el 22/09/2026, y conviene saber por qué se
        # pudo.
        #
        # Era una segunda fuente de verdad sobre «qué rol tiene esta persona
        # aquí», y tenía un fallo propio: a un master al que le borraban la
        # membresía **no se le quitaba el rol**.
        #
        # Lo que autorizó quitarlo fue una medida, no una opinión. El contador
        # (a) del runbook de la 029 —masters con organización **real** y sin
        # membresía en ella— dio **0** contra producción el 21/09. Lo único que
        # el *fallback* sostenía eran los siete huérfanos, cuya
        # `organization_id` apunta a una organización que no existe; a ésos les
        # devolvía «OWNER de una organización que no está». Al quitarlo pasan a
        # `None`, que no es menos acceso: es el mismo, dicho con verdad.
        #
        # Si algún día ese contador deja de ser 0, la respuesta no es devolver
        # el *fallback* sino crear la membresía que falta.
        return None

    @staticmethod
    def is_member(
        db: Session,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """Verifica si un usuario es miembro de una organización."""
        role = OrganizationService.get_user_role(db, user_id, organization_id)
        return role is not None

    @staticmethod
    def can_manage_users(
        db: Session,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """
        Verifica si el usuario puede gestionar otros usuarios.

        Roles permitidos: owner, admin
        """
        role = OrganizationService.get_user_role(db, user_id, organization_id)
        if role is None:
            return False
        return role in [OrganizationRole.OWNER, OrganizationRole.ADMIN]

    @staticmethod
    def can_manage_billing(
        db: Session,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """
        Verifica si el usuario puede gestionar facturación.

        Roles permitidos: owner, billing
        """
        role = OrganizationService.get_user_role(db, user_id, organization_id)
        if role is None:
            return False
        return role in [OrganizationRole.OWNER, OrganizationRole.BILLING]

    @staticmethod
    def can_manage_organization(
        db: Session,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """
        Verifica si el usuario puede gestionar la organización.

        Solo el owner puede hacer esto.
        """
        role = OrganizationService.get_user_role(db, user_id, organization_id)
        return role == OrganizationRole.OWNER

    @staticmethod
    def is_owner(
        db: Session,
        user_id: UUID,
        organization_id: UUID,
    ) -> bool:
        """Verifica si el usuario es el owner de la organización."""
        role = OrganizationService.get_user_role(db, user_id, organization_id)
        return role == OrganizationRole.OWNER

    @staticmethod
    def get_organization_members(
        db: Session,
        organization_id: UUID,
    ) -> list[dict]:
        """
        Obtiene todos los miembros de una organización con sus roles.

        Returns:
            Lista de diccionarios con información de cada miembro
        """
        memberships = (
            db.query(OrganizationUser, User)
            .join(User, OrganizationUser.user_id == User.id)
            .filter(OrganizationUser.organization_id == organization_id)
            .all()
        )

        result = []
        for membership, user in memberships:
            result.append(
                {
                    "user_id": str(user.id),
                    "email": user.email,
                    "full_name": user.full_name,
                    "role": membership.role,
                    "joined_at": (
                        membership.created_at.isoformat()
                        if membership.created_at
                        else None
                    ),
                    "email_verified": user.email_verified,
                }
            )

        return result

    @staticmethod
    def add_member(
        db: Session,
        organization_id: UUID,
        user_id: UUID,
        role: OrganizationRole = OrganizationRole.MEMBER,
    ) -> OrganizationUser:
        """
        Agrega un miembro a la organización.

        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            user_id: ID del usuario
            role: Rol a asignar

        Returns:
            El registro de OrganizationUser creado
        """
        # Verificar que no exista ya
        existing = (
            db.query(OrganizationUser)
            .filter(
                OrganizationUser.organization_id == organization_id,
                OrganizationUser.user_id == user_id,
            )
            .first()
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El usuario ya es miembro de esta organización",
            )

        # Verificar que solo haya un owner
        if role == OrganizationRole.OWNER:
            existing_owner = (
                db.query(OrganizationUser)
                .filter(
                    OrganizationUser.organization_id == organization_id,
                    OrganizationUser.role == OrganizationRole.OWNER.value,
                )
                .first()
            )
            if existing_owner:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Ya existe un owner para esta organización",
                )

        membership = OrganizationUser(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )

        db.add(membership)
        db.commit()
        db.refresh(membership)

        return membership

    @staticmethod
    def update_member_role(
        db: Session,
        organization_id: UUID,
        user_id: UUID,
        new_role: OrganizationRole,
        performed_by_user_id: UUID,
    ) -> OrganizationUser:
        """
        Actualiza el rol de un miembro.

        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            user_id: ID del usuario a modificar
            new_role: Nuevo rol
            performed_by_user_id: ID del usuario que realiza la acción

        Returns:
            El registro de OrganizationUser actualizado
        """
        # Verificar que quien hace el cambio tenga permisos
        if not OrganizationService.can_manage_users(
            db, performed_by_user_id, organization_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para gestionar usuarios",
            )

        membership = (
            db.query(OrganizationUser)
            .filter(
                OrganizationUser.organization_id == organization_id,
                OrganizationUser.user_id == user_id,
            )
            .first()
        )

        if not membership:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado en la organización",
            )

        # No se puede cambiar el rol del owner
        if membership.role == OrganizationRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede cambiar el rol del owner",
            )

        # No se puede asignar owner a otro usuario
        if new_role == OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede asignar el rol de owner",
            )

        membership.role = new_role
        db.commit()
        db.refresh(membership)

        return membership

    @staticmethod
    def remove_member(
        db: Session,
        organization_id: UUID,
        user_id: UUID,
        performed_by_user_id: UUID,
    ) -> bool:
        """
        Remueve un miembro de la organización.

        Args:
            db: Sesión de base de datos
            organization_id: ID de la organización
            user_id: ID del usuario a remover
            performed_by_user_id: ID del usuario que realiza la acción

        Returns:
            True si se removió correctamente
        """
        # Verificar permisos
        if not OrganizationService.can_manage_users(
            db, performed_by_user_id, organization_id
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="No tienes permisos para gestionar usuarios",
            )

        membership = (
            db.query(OrganizationUser)
            .filter(
                OrganizationUser.organization_id == organization_id,
                OrganizationUser.user_id == user_id,
            )
            .first()
        )

        if not membership:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Usuario no encontrado en la organización",
            )

        # No se puede remover al owner
        if membership.role == OrganizationRole.OWNER.value:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No se puede remover al owner de la organización",
            )

        db.delete(membership)
        db.commit()

        return True

    @staticmethod
    def get_active_subscriptions(
        db: Session,
        organization_id: UUID,
    ) -> list[Subscription]:
        """
        Obtiene las suscripciones activas de una organización.

        DELEGACIÓN: Esta función delega a subscription_query.get_active_subscriptions()
        que es la ÚNICA fuente de verdad para la regla de suscripción activa.

        Returns:
            Lista de suscripciones activas, ordenadas por started_at DESC
        """
        return _get_active_subscriptions(db, organization_id)

    @staticmethod
    def get_subscription_history(
        db: Session,
        organization_id: UUID,
        limit: int = 20,
    ) -> list[Subscription]:
        """
        Obtiene el historial de suscripciones de una organización.

        DELEGACIÓN: Esta función delega a subscription_query.get_subscription_history()

        Returns:
            Lista de suscripciones (activas e históricas)
        """
        return _get_subscription_history(db, organization_id, limit)

    @staticmethod
    def get_organization_summary(
        db: Session,
        organization_id: UUID,
    ) -> dict:
        """
        Obtiene un resumen completo de la organización.

        Incluye: información básica, suscripciones activas, conteo de miembros
        """
        organization = (
            db.query(Organization).filter(Organization.id == organization_id).first()
        )

        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organización no encontrada",
            )

        active_subs = OrganizationService.get_active_subscriptions(db, organization_id)
        members_count = (
            db.query(OrganizationUser)
            .filter(OrganizationUser.organization_id == organization_id)
            .count()
        )

        return {
            "organization": {
                "id": str(organization.id),
                "account_id": (
                    str(organization.account_id) if organization.account_id else None
                ),
                "name": organization.name,
                "status": organization.status,
                "billing_email": organization.billing_email,
                "country": organization.country,
                "timezone": organization.timezone,
                "created_at": (
                    organization.created_at.isoformat()
                    if organization.created_at
                    else None
                ),
            },
            "subscriptions": {
                "active": [
                    {
                        "id": str(sub.id),
                        "plan_id": str(sub.plan_id),
                        "status": sub.status,
                        "expires_at": (
                            sub.expires_at.isoformat() if sub.expires_at else None
                        ),
                        "auto_renew": sub.auto_renew,
                    }
                    for sub in active_subs
                ],
                "active_count": len(active_subs),
            },
            "members": {
                "count": members_count,
            },
        }


# =====================================================
# Funciones de conveniencia
# =====================================================


def get_user_role(
    db: Session, user_id: UUID, organization_id: UUID
) -> Optional[OrganizationRole]:
    """Atajo para OrganizationService.get_user_role"""
    return OrganizationService.get_user_role(db, user_id, organization_id)


def can_manage_users(db: Session, user_id: UUID, organization_id: UUID) -> bool:
    """Atajo para OrganizationService.can_manage_users"""
    return OrganizationService.can_manage_users(db, user_id, organization_id)


def can_manage_billing(db: Session, user_id: UUID, organization_id: UUID) -> bool:
    """Atajo para OrganizationService.can_manage_billing"""
    return OrganizationService.can_manage_billing(db, user_id, organization_id)


# =====================================================
# Aliases de compatibilidad (DEPRECATED)
# =====================================================


def get_user_role_for_client(
    db: Session, user_id: UUID, client_id: UUID
) -> Optional[OrganizationRole]:
    """DEPRECATED: Usar get_user_role con organization_id"""
    return get_user_role(db, user_id, client_id)


def can_manage_users_for_client(db: Session, user_id: UUID, client_id: UUID) -> bool:
    """DEPRECATED: Usar can_manage_users con organization_id"""
    return can_manage_users(db, user_id, client_id)


def can_manage_billing_for_client(db: Session, user_id: UUID, client_id: UUID) -> bool:
    """DEPRECATED: Usar can_manage_billing con organization_id"""
    return can_manage_billing(db, user_id, client_id)
