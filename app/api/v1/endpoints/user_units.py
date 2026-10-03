from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user_full,
    get_scope_store,
    get_user_units_kafka_producer,
)
from app.db.session import get_db
from app.models.unit import Unit
from app.models.user import User
from app.models.user_unit import UserUnit
from app.schemas.user_unit import UserUnitCreate, UserUnitDetail, UserUnitOut
from app.services.data_token_issuance import revoke_sessions_for_user
from app.services.messaging.control_events import (
    build_user_unit_event,
    publish_control_event,
)
from app.services.messaging.kafka_producer import UserUnitsKafkaProducer

router = APIRouter()


# ============================================
# Helper Functions
# ============================================


def require_master(user: User):
    """Verifica que el usuario sea maestro"""
    if not user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios maestros pueden gestionar permisos de unidades",
        )


# ============================================
# User-Unit Endpoints
# ============================================


@router.get("", response_model=List[UserUnitDetail])
def list_user_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    unit_id: Optional[UUID] = None,
    user_id: Optional[UUID] = None,
):
    """
    Lista todas las asignaciones usuario→unidad del cliente.

    Requiere: Usuario maestro del cliente.

    Parámetros opcionales:
    - unit_id: Filtrar por unidad específica
    - user_id: Filtrar por usuario específico

    Retorna información detallada incluyendo nombres y emails.
    """
    require_master(current_user)

    # Base query: solo asignaciones de unidades del cliente
    query = (
        db.query(UserUnit)
        .join(Unit, UserUnit.unit_id == Unit.id)
        .filter(
            Unit.organization_id == current_user.organization_id,
            Unit.deleted_at.is_(None),
        )
    )

    # Filtros opcionales
    if unit_id:
        query = query.filter(UserUnit.unit_id == unit_id)

    if user_id:
        query = query.filter(UserUnit.user_id == user_id)

    assignments = query.order_by(UserUnit.granted_at.desc()).all()

    # Construir respuesta detallada
    result = []
    for assignment in assignments:
        # Obtener información del usuario
        user = db.query(User).filter(User.id == assignment.user_id).first()
        unit = db.query(Unit).filter(Unit.id == assignment.unit_id).first()
        granted_by_user = None
        if assignment.granted_by:
            granted_by_user = (
                db.query(User).filter(User.id == assignment.granted_by).first()
            )

        detail = UserUnitDetail(
            id=assignment.id,
            user_id=assignment.user_id,
            unit_id=assignment.unit_id,
            unit_ref=unit.unit_ref if unit else None,
            granted_by=assignment.granted_by,
            granted_at=assignment.granted_at,
            role=assignment.role,
            user_email=user.email if user else None,
            user_full_name=user.full_name if user else None,
            unit_name=unit.name if unit else None,
            granted_by_email=granted_by_user.email if granted_by_user else None,
        )
        result.append(detail)

    return result


@router.post("", response_model=UserUnitOut, status_code=status.HTTP_201_CREATED)
def create_user_unit(
    assignment: UserUnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    user_units_kafka_producer: UserUnitsKafkaProducer = Depends(
        get_user_units_kafka_producer
    ),
):
    """
    Otorga acceso de un usuario a una unidad.

    Requiere: Usuario maestro del cliente.

    Validaciones:
    - El usuario debe pertenecer al mismo cliente
    - La unidad debe pertenecer al cliente
    - El usuario no debe ser maestro (los maestros ya tienen acceso a todo)
    - No debe existir una asignación previa (unicidad user_id + unit_id)

    Registra quién otorgó el permiso en granted_by.
    """
    require_master(current_user)

    # Verificar que el usuario existe y pertenece al cliente
    target_user = (
        db.query(User)
        .filter(
            User.id == assignment.user_id,
            User.default_organization_id == current_user.organization_id,
        )
        .first()
    )

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado o no pertenece a tu cliente",
        )

    # No permitir asignar a usuarios maestros
    if target_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No es necesario asignar permisos a usuarios maestros (ya tienen acceso a todas las unidades)",
        )

    # Verificar que la unidad existe y pertenece al cliente
    unit = (
        db.query(Unit)
        .filter(
            Unit.id == assignment.unit_id,
            Unit.organization_id == current_user.organization_id,
            Unit.deleted_at.is_(None),
        )
        .first()
    )

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unidad no encontrada o no pertenece a tu cliente",
        )

    # Verificar que no existe una asignación previa
    existing = (
        db.query(UserUnit)
        .filter(
            UserUnit.user_id == assignment.user_id,
            UserUnit.unit_id == assignment.unit_id,
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario ya tiene acceso a esta unidad con rol '{existing.role}'",
        )

    # Validar rol
    valid_roles = ["viewer", "editor", "admin"]
    if assignment.role not in valid_roles:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Rol inválido. Debe ser uno de: {', '.join(valid_roles)}",
        )

    # Crear la asignación
    user_unit = UserUnit(
        user_id=assignment.user_id,
        unit_id=assignment.unit_id,
        role=assignment.role,
        granted_by=current_user.id,
    )
    db.add(user_unit)
    db.commit()
    db.refresh(user_unit)

    publish_control_event(
        user_units_kafka_producer,
        build_user_unit_event(
            event_type="UPSERT",
            organization_id=current_user.organization_id,
            user_id=user_unit.user_id,
            unit_id=user_unit.unit_id,
            role=user_unit.role,
        ),
        key=str(user_unit.user_id),
        endpoint="create_user_unit",
    )

    return user_unit


@router.delete("/{assignment_id}", status_code=status.HTTP_200_OK)
def delete_user_unit(
    assignment_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    user_units_kafka_producer: UserUnitsKafkaProducer = Depends(
        get_user_units_kafka_producer
    ),
    store=Depends(get_scope_store),
):
    """
    Revoca el acceso de un usuario a una unidad.

    Requiere: Usuario maestro del cliente.

    Elimina físicamente el registro (no es soft delete).
    """
    require_master(current_user)

    # Verificar que la asignación existe y pertenece al cliente
    assignment = (
        db.query(UserUnit)
        .join(Unit, UserUnit.unit_id == Unit.id)
        .filter(
            UserUnit.id == assignment_id,
            Unit.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Asignación no encontrada"
        )

    # Obtener información para el mensaje
    user = db.query(User).filter(User.id == assignment.user_id).first()
    unit = db.query(Unit).filter(Unit.id == assignment.unit_id).first()

    revoked_user_id = assignment.user_id
    revoked_unit_id = assignment.unit_id

    # Eliminar la asignación
    db.delete(assignment)
    db.commit()

    publish_control_event(
        user_units_kafka_producer,
        build_user_unit_event(
            event_type="DELETE",
            organization_id=current_user.organization_id,
            user_id=revoked_user_id,
            unit_id=revoked_unit_id,
        ),
        key=str(revoked_user_id),
        endpoint="delete_user_unit",
    )

    # El permiso ya está retirado en Postgres; esto adelanta el momento en que el
    # plano de datos se entera. Best effort: si Valkey no responde, el alcance
    # viejo caduca solo y no tiene sentido fallar una operación ya completada.
    revoke_sessions_for_user(store, revoked_user_id)

    return {
        "message": "Acceso revocado exitosamente",
        "assignment_id": str(assignment_id),
        "user_email": user.email if user else None,
        "unit_name": unit.name if unit else None,
    }
