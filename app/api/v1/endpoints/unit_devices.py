from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import get_current_organization_id, get_current_user_id
from app.db.session import get_db
from app.models.device import Device, DeviceEvent
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.schemas.unit_device import UnitDeviceCreate, UnitDeviceDetail, UnitDeviceOut

router = APIRouter()


# ============================================
# Helper Functions
# ============================================


def create_device_event(
    db: Session,
    device_id: str,
    event_type: str,
    old_status: str = None,
    new_status: str = None,
    performed_by: UUID = None,
    event_details: str = None,
) -> DeviceEvent:
    """Crea un registro de evento para un dispositivo"""
    event = DeviceEvent(
        device_id=device_id,
        event_type=event_type,
        old_status=old_status,
        new_status=new_status,
        performed_by=performed_by,
        event_details=event_details,
    )
    db.add(event)
    return event


# ============================================
# Unit-Device Endpoints
# ============================================


@router.get("", response_model=List[UnitDeviceOut])
def list_unit_devices(
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
    active_only: bool = True,
):
    """
    Lista todas las relaciones unit-device de la organización.

    Por defecto solo muestra las activas (unassigned_at IS NULL).
    Usa active_only=false para ver todas incluyendo históricas.

    Requiere: Usuario de la organización autenticado.
    """
    # Subconsulta para obtener units de la organización
    org_units = (
        db.query(Unit.id).filter(Unit.organization_id == organization_id).subquery()
    )

    query = db.query(UnitDevice).filter(UnitDevice.unit_id.in_(org_units))

    if active_only:
        query = query.filter(UnitDevice.unassigned_at.is_(None))

    assignments = query.order_by(UnitDevice.assigned_at.desc()).all()
    return assignments


@router.post("", response_model=UnitDeviceOut, status_code=status.HTTP_201_CREATED)
def create_unit_device(
    assignment: UnitDeviceCreate,
    organization_id: UUID = Depends(get_current_organization_id),
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Asigna un dispositivo a una unidad.

    Validaciones:
    - La unidad debe pertenecer a la organización autenticada
    - El dispositivo debe pertenecer a la organización autenticada
    - El dispositivo debe estar en estado 'entregado' o 'devuelto'
    - No debe existir una asignación activa previa

    Al asignar:
    - Crea registro en unit_devices
    - Actualiza device.status = 'asignado'
    - Actualiza device.last_assignment_at
    - Crea evento en device_events
    """
    # Verificar que la unidad existe y pertenece a la organización
    unit = (
        db.query(Unit)
        .filter(Unit.id == assignment.unit_id, Unit.organization_id == organization_id)
        .first()
    )

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Unidad no encontrada o no pertenece a tu organización",
        )

    # Verificar que el dispositivo existe y pertenece a la organización
    device = (
        db.query(Device)
        .filter(
            Device.device_id == assignment.device_id,
            Device.organization_id == organization_id,
        )
        .first()
    )

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado o no pertenece a tu organización",
        )

    # Validar estado del dispositivo
    if device.status not in ["entregado", "devuelto"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "El dispositivo debe estar en estado 'entregado' o 'devuelto' "
                f"(estado actual: {device.status})"
            ),
        )

    # Verificar que no existe una asignación activa
    existing = (
        db.query(UnitDevice)
        .filter(
            UnitDevice.device_id == assignment.device_id,
            UnitDevice.unassigned_at.is_(None),
        )
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El dispositivo ya está asignado a una unidad activa",
        )

    # Reutilizar una asignación histórica si ya existe para esta unidad-dispositivo
    now = datetime.utcnow()
    unit_device = (
        db.query(UnitDevice)
        .filter(
            UnitDevice.unit_id == assignment.unit_id,
            UnitDevice.device_id == assignment.device_id,
        )
        .first()
    )

    if unit_device:
        if unit_device.unassigned_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El dispositivo ya está asignado a esta unidad",
            )

        unit_device.assigned_at = now
        unit_device.unassigned_at = None
        db.add(unit_device)
    else:
        unit_device = UnitDevice(
            unit_id=assignment.unit_id,
            device_id=assignment.device_id,
            assigned_at=now,
        )
        db.add(unit_device)

    # Actualizar estado del dispositivo
    old_status = device.status
    device.status = "asignado"
    device.last_assignment_at = now
    db.add(device)

    # Crear evento
    create_device_event(
        db=db,
        device_id=device.device_id,
        event_type="asignado",
        old_status=old_status,
        new_status="asignado",
        performed_by=user_id,
        event_details=f"Dispositivo asignado a unidad '{unit.name}'",
    )

    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Conflicto al asignar dispositivo. Intenta nuevamente.",
        )

    db.refresh(unit_device)

    return unit_device


@router.get("/{assignment_id}", response_model=UnitDeviceDetail)
def get_unit_device(
    assignment_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id),
    db: Session = Depends(get_db),
):
    """
    Obtiene el detalle de una asignación específica.

    Incluye información adicional de la unidad y el dispositivo.
    """
    # Subconsulta para obtener units de la organización
    org_units = (
        db.query(Unit.id).filter(Unit.organization_id == organization_id).subquery()
    )

    assignment = (
        db.query(UnitDevice)
        .filter(UnitDevice.id == assignment_id, UnitDevice.unit_id.in_(org_units))
        .first()
    )

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Asignación no encontrada"
        )

    # Obtener información adicional
    unit = db.query(Unit).filter(Unit.id == assignment.unit_id).first()
    device = db.query(Device).filter(Device.device_id == assignment.device_id).first()

    # Construir respuesta detallada
    detail = UnitDeviceDetail(
        id=assignment.id,
        unit_id=assignment.unit_id,
        device_id=assignment.device_id,
        assigned_at=assignment.assigned_at,
        unassigned_at=assignment.unassigned_at,
        unit_name=unit.name if unit else None,
        device_brand=device.brand if device else None,
        device_model=device.model if device else None,
        device_status=device.status if device else None,
    )

    return detail


@router.delete("/{assignment_id}", status_code=status.HTTP_200_OK)
def delete_unit_device(
    assignment_id: UUID,
    organization_id: UUID = Depends(get_current_organization_id),
    user_id: UUID = Depends(get_current_user_id),
    db: Session = Depends(get_db),
):
    """
    Desasigna un dispositivo de una unidad.

    No elimina el registro, solo marca unassigned_at = NOW().
    Actualiza el estado del dispositivo según corresponda.

    Reglas:
    - Si el dispositivo no tiene otras asignaciones activas → status = 'entregado'
    - Crea evento en device_events
    """
    # Subconsulta para obtener units de la organización
    org_units = (
        db.query(Unit.id).filter(Unit.organization_id == organization_id).subquery()
    )

    assignment = (
        db.query(UnitDevice)
        .filter(UnitDevice.id == assignment_id, UnitDevice.unit_id.in_(org_units))
        .first()
    )

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Asignación no encontrada"
        )

    # Verificar que está activa
    if assignment.unassigned_at is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Esta asignación ya fue desactivada",
        )

    # Obtener información para el evento
    unit = db.query(Unit).filter(Unit.id == assignment.unit_id).first()
    device = db.query(Device).filter(Device.device_id == assignment.device_id).first()

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dispositivo no encontrado"
        )

    # Desasignar
    assignment.unassigned_at = datetime.utcnow()
    db.add(assignment)

    # Actualizar estado del dispositivo
    old_status = device.status
    device.status = "entregado"  # Vuelve a estado entregado
    db.add(device)

    # Crear evento
    create_device_event(
        db=db,
        device_id=device.device_id,
        event_type="estado_cambiado",
        old_status=old_status,
        new_status="entregado",
        performed_by=user_id,
        event_details=f"Dispositivo desasignado de unidad '{unit.name if unit else 'desconocida'}'",
    )

    db.commit()

    return {
        "message": "Dispositivo desasignado exitosamente",
        "assignment_id": str(assignment_id),
        "device_id": assignment.device_id,
        "unassigned_at": assignment.unassigned_at.isoformat(),
    }
