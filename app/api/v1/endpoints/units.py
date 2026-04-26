from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_user_full,
    get_current_user_id,
)
from app.core.config import settings
from app.db.session import get_db
from app.models.device import Device, DeviceEvent
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.unit_profile import UnitProfile
from app.models.user import User
from app.models.user_unit import UserUnit
from app.models.vehicle_profile import VehicleProfile
from app.schemas.device import DeviceOut
from app.schemas.unit import (
    ShareLocationResponse,
    UnitCreate,
    UnitDetail,
    UnitOut,
    UnitUpdate,
    UnitWithDevice,
)
from app.schemas.unit_device import UnitDeviceAssign, UnitDeviceOut
from app.schemas.unit_profile import UnitProfileComplete, UnitProfileUpdate
from app.schemas.user_unit import UserUnitAssign, UserUnitDetail
from app.schemas.vehicle_profile import (
    VehicleProfileCreate,
    VehicleProfileOut,
    VehicleProfileUpdate,
)
from app.utils.paseto_token import generate_location_share_token

router = APIRouter()


# ============================================
# Helper Functions
# ============================================


def check_unit_access(
    db: Session, unit_id: UUID, user: User, required_role: str = None
) -> Unit:
    """
    Verifica que el usuario tenga acceso a la unidad.

    - Si es maestro: tiene acceso a todas las unidades del cliente
    - Si no es maestro: debe tener un registro en user_units
    - Si se especifica required_role: valida que tenga ese rol o superior

    Retorna la unidad si tiene acceso, lanza HTTPException si no.
    """
    # Obtener la unidad
    unit = (
        db.query(Unit)
        .filter(
            Unit.id == unit_id,
            Unit.organization_id == user.organization_id,
            Unit.deleted_at.is_(None),
        )
        .first()
    )

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unidad no encontrada"
        )

    # Si es maestro, tiene acceso total
    if user.is_master:
        return unit

    # Si no es maestro, verificar en user_units
    user_unit = (
        db.query(UserUnit)
        .filter(UserUnit.user_id == user.id, UserUnit.unit_id == unit_id)
        .first()
    )

    if not user_unit:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tienes permiso para acceder a esta unidad",
        )

    # Validar rol si se requiere
    if required_role:
        role_hierarchy = {"viewer": 0, "editor": 1, "admin": 2}
        user_role_level = role_hierarchy.get(user_unit.role, 0)
        required_level = role_hierarchy.get(required_role, 0)

        if user_role_level < required_level:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Se requiere rol '{required_role}' o superior",
            )

    return unit


def get_units_for_user(db: Session, user: User, include_deleted: bool = False):
    """
    Retorna las unidades visibles para el usuario.

    - Si es maestro: todas las de la organización
    - Si no es maestro: solo las que tiene en user_units
    """
    query = db.query(Unit).filter(Unit.organization_id == user.organization_id)

    if not include_deleted:
        query = query.filter(Unit.deleted_at.is_(None))

    if user.is_master:
        # Maestro ve todas las unidades del cliente
        return query.all()
    else:
        # Usuario normal ve solo las unidades con permisos
        user_unit_ids = (
            db.query(UserUnit.unit_id).filter(UserUnit.user_id == user.id).subquery()
        )

        return query.filter(Unit.id.in_(user_unit_ids)).all()


# ============================================
# Unit Endpoints
# ============================================


@router.get("", response_model=List[UnitWithDevice])
def list_units(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    include_deleted: bool = False,
):
    """
    Lista las unidades visibles para el usuario autenticado con información del dispositivo asignado.

    - Si es maestro → todas las unidades del cliente
    - Si no es maestro → solo las unidades en user_units

    Incluye información del dispositivo actualmente asignado (si existe).

    Parámetros:
    - include_deleted: incluir unidades eliminadas (solo para maestros)
    """
    # Construir query base con LEFT JOINs optimizados
    query = (
        db.query(
            Unit.id,
            Unit.organization_id,
            Unit.name,
            func.coalesce(UnitProfile.description, Unit.description).label(
                "description"
            ),
            Unit.deleted_at,
            Device.device_id,
            Device.brand.label("device_brand"),
            Device.model.label("device_model"),
            UnitDevice.assigned_at,
            UnitProfile.icon_type,
            UnitProfile.brand,
            UnitProfile.model,
            UnitProfile.color,
            UnitProfile.year,
            VehicleProfile.plate,
            VehicleProfile.vin,
        )
        .outerjoin(UnitProfile, UnitProfile.unit_id == Unit.id)
        .outerjoin(VehicleProfile, VehicleProfile.unit_id == Unit.id)
        .outerjoin(
            UnitDevice,
            (UnitDevice.unit_id == Unit.id) & (UnitDevice.unassigned_at.is_(None)),
        )
        .outerjoin(Device, Device.device_id == UnitDevice.device_id)
        .filter(Unit.organization_id == current_user.organization_id)
    )

    # Filtrar unidades eliminadas (solo maestros pueden ver eliminadas)
    if not include_deleted or not current_user.is_master:
        query = query.filter(Unit.deleted_at.is_(None))

    # Aplicar lógica de visibilidad según tipo de usuario
    if not current_user.is_master:
        # Usuario NO maestro: solo ve unidades en user_units
        user_unit_ids = (
            db.query(UserUnit.unit_id)
            .filter(UserUnit.user_id == current_user.id)
            .subquery()
        )
        query = query.filter(Unit.id.in_(user_unit_ids))
    # Usuario maestro: ve todas las unidades del cliente (sin filtros adicionales)

    # Ejecutar query única (sin N+1 queries)
    results = query.all()

    # Construir respuesta con los datos del JOIN
    units = []
    for row in results:
        unit = UnitWithDevice(
            id=row.id,
            client_id=row.organization_id,
            name=row.name,
            description=row.description,
            deleted_at=row.deleted_at,
            device_id=row.device_id,
            device_brand=row.device_brand,
            device_model=row.device_model,
            assigned_at=row.assigned_at,
            icon_type=row.icon_type,
            brand=row.brand,
            model=row.model,
            color=row.color,
            year=row.year,
            plate=row.plate,
            vin=row.vin,
        )
        units.append(unit)

    return units


@router.post("", response_model=UnitOut, status_code=status.HTTP_201_CREATED)
def create_unit(
    unit: UnitCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Crea una nueva unidad.

    Requiere: Usuario maestro del cliente.

    Automáticamente crea un unit_profile con unit_type="vehicle" por defecto.
    Si el body incluye datos de perfil/dispositivo, los crea/asigna en la misma transacción.
    """
    # Validar que sea maestro
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios maestros pueden crear unidades",
        )

    # Validar dispositivo opcional antes de crear registros
    device = None
    if unit.device_id:
        device = (
            db.query(Device)
            .filter(
                Device.device_id == unit.device_id,
                Device.organization_id == current_user.organization_id,
            )
            .first()
        )

        if not device:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Dispositivo no encontrado o no pertenece a tu organización",
            )

        if device.status not in ["entregado", "devuelto"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"El dispositivo debe estar en estado 'entregado' o 'devuelto' (estado actual: {device.status})",
            )

        existing_assignment = (
            db.query(UnitDevice)
            .filter(
                UnitDevice.device_id == unit.device_id,
                UnitDevice.unassigned_at.is_(None),
            )
            .first()
        )

        if existing_assignment:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El dispositivo ya está asignado a otra unidad activa",
            )

    # Crear la unidad
    new_unit = Unit(
        organization_id=current_user.organization_id,
        name=unit.name,
        description=unit.description,
    )
    db.add(new_unit)
    db.flush()  # Flush para obtener el ID sin hacer commit aún

    # Crear unit_profile automáticamente
    unit_profile = UnitProfile(
        unit_id=new_unit.id,
        unit_type="vehicle",  # Tipo por defecto
        icon_type=unit.icon_type,
        brand=unit.brand,
        model=unit.model,
        color=unit.color,
        year=unit.year,
    )
    db.add(unit_profile)

    # Crear vehicle_profile si llegan datos de vehículo
    if unit.plate is not None or unit.vin is not None:
        vehicle_profile = VehicleProfile(
            unit_id=new_unit.id,
            plate=unit.plate,
            vin=unit.vin,
        )
        db.add(vehicle_profile)

    # Asignar dispositivo opcional
    if device:
        now = datetime.utcnow()

        new_assignment = UnitDevice(
            unit_id=new_unit.id,
            device_id=device.device_id,
            assigned_at=now,
        )
        db.add(new_assignment)

        old_status = device.status
        device.status = "asignado"
        device.last_assignment_at = now
        db.add(device)

        create_device_event(
            db=db,
            device_id=device.device_id,
            event_type="asignado",
            old_status=old_status,
            new_status="asignado",
            performed_by=user_id,
            event_details=f"Dispositivo asignado a unidad '{new_unit.name}'",
        )

    # Commit de ambos
    db.commit()
    db.refresh(new_unit)

    return new_unit


@router.get("/{unit_id}", response_model=UnitDetail)
def get_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Obtiene el detalle de una unidad.

    Incluye contadores de dispositivos asignados.
    Requiere: Acceso a la unidad (maestro o en user_units).
    """
    # Verificar acceso
    unit = check_unit_access(db, unit_id, current_user)

    # Contar dispositivos
    active_devices = (
        db.query(UnitDevice)
        .filter(UnitDevice.unit_id == unit_id, UnitDevice.unassigned_at.is_(None))
        .count()
    )

    total_devices = db.query(UnitDevice).filter(UnitDevice.unit_id == unit_id).count()

    # Construir respuesta
    detail = UnitDetail(
        id=unit.id,
        client_id=unit.client_id,
        name=unit.name,
        description=unit.description,
        deleted_at=unit.deleted_at,
        active_devices_count=active_devices,
        total_devices_count=total_devices,
    )

    return detail


@router.patch("/{unit_id}", response_model=UnitOut)
def update_unit(
    unit_id: UUID,
    unit_update: UnitUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Actualiza los datos de una unidad.

    Requiere:
    - Usuario maestro, o
    - Usuario con rol 'editor' o 'admin' en user_units
    """
    # Verificar acceso con rol editor o superior
    unit = check_unit_access(db, unit_id, current_user, required_role="editor")

    # Actualizar campos
    update_data = unit_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(unit, field, value)

    db.add(unit)
    db.commit()
    db.refresh(unit)

    return unit


@router.delete("/{unit_id}", status_code=status.HTTP_200_OK)
def delete_unit(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Marca una unidad como eliminada (soft delete).

    No elimina físicamente el registro, solo marca deleted_at = NOW().

    Requiere: Usuario maestro del cliente.
    """
    # Solo maestros pueden eliminar
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios maestros pueden eliminar unidades",
        )

    # Verificar que la unidad existe y pertenece al cliente
    unit = (
        db.query(Unit)
        .filter(
            Unit.id == unit_id,
            Unit.organization_id == current_user.organization_id,
            Unit.deleted_at.is_(None),
        )
        .first()
    )

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unidad no encontrada"
        )

    # Verificar si tiene dispositivos activos
    active_devices = (
        db.query(UnitDevice)
        .filter(UnitDevice.unit_id == unit_id, UnitDevice.unassigned_at.is_(None))
        .count()
    )

    if active_devices > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se puede eliminar la unidad porque tiene {active_devices} dispositivo(s) activo(s) asignado(s)",
        )

    # Marcar como eliminada
    unit.deleted_at = datetime.utcnow()
    db.add(unit)
    db.commit()

    return {
        "message": "Unidad eliminada exitosamente",
        "unit_id": str(unit_id),
        "deleted_at": unit.deleted_at.isoformat(),
    }


# ============================================
# Hierarchical Endpoints (Nested Resources)
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


@router.get("/{unit_id}/device", response_model=Optional[DeviceOut])
def get_unit_device(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Devuelve el dispositivo actualmente asignado a una unidad.

    Requiere: Acceso a la unidad (maestro o en user_units).

    Retorna None si no hay dispositivo asignado actualmente.
    """
    # Verificar acceso a la unidad
    check_unit_access(db, unit_id, current_user)

    # Buscar asignación activa
    active_assignment = (
        db.query(UnitDevice)
        .filter(UnitDevice.unit_id == unit_id, UnitDevice.unassigned_at.is_(None))
        .first()
    )

    if not active_assignment:
        return None

    # Obtener información del dispositivo
    device = (
        db.query(Device).filter(Device.device_id == active_assignment.device_id).first()
    )

    return device


@router.post(
    "/{unit_id}/device",
    response_model=UnitDeviceOut,
    status_code=status.HTTP_201_CREATED,
)
def assign_device_to_unit(
    unit_id: UUID,
    assignment: UnitDeviceAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    user_id: UUID = Depends(get_current_user_id),
):
    """
    Asigna o reemplaza el dispositivo de una unidad.

    Requiere: Usuario maestro O rol 'editor'/'admin' en user_units.

    Comportamiento:
    - Si la unidad ya tiene un dispositivo activo, lo desasigna automáticamente
    - Asigna el nuevo dispositivo
    - Actualiza el estado del dispositivo a 'asignado'
    - Crea eventos en device_events

    Body (JSON):
    {
        "device_id": "864537040123456"
    }
    """
    # Verificar acceso con rol editor o superior
    unit = check_unit_access(db, unit_id, current_user, required_role="editor")

    # Verificar que el dispositivo existe y pertenece a la organización
    device = (
        db.query(Device)
        .filter(
            Device.device_id == assignment.device_id,
            Device.organization_id == current_user.organization_id,
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
            detail=f"El dispositivo debe estar en estado 'entregado' o 'devuelto' (estado actual: {device.status})",
        )

    # Si la unidad ya tiene un dispositivo activo, desasignarlo primero
    current_assignment = (
        db.query(UnitDevice)
        .filter(UnitDevice.unit_id == unit_id, UnitDevice.unassigned_at.is_(None))
        .first()
    )

    if current_assignment:
        # Desasignar dispositivo anterior
        current_assignment.unassigned_at = datetime.utcnow()
        db.add(current_assignment)

        # Actualizar estado del dispositivo anterior
        old_device = (
            db.query(Device)
            .filter(Device.device_id == current_assignment.device_id)
            .first()
        )

        if old_device:
            old_device.status = "entregado"
            db.add(old_device)

            create_device_event(
                db=db,
                device_id=old_device.device_id,
                event_type="estado_cambiado",
                old_status="asignado",
                new_status="entregado",
                performed_by=user_id,
                event_details=f"Dispositivo desasignado de unidad '{unit.name}' (reemplazo)",
            )

    # Verificar que el nuevo dispositivo no esté asignado en otra unidad
    existing_assignment = (
        db.query(UnitDevice)
        .filter(
            UnitDevice.device_id == assignment.device_id,
            UnitDevice.unassigned_at.is_(None),
        )
        .first()
    )

    if existing_assignment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El dispositivo ya está asignado a otra unidad activa",
        )

    now = datetime.utcnow()

    # Reutilizar una asignación histórica si ya existe para esta unidad-dispositivo
    new_assignment = (
        db.query(UnitDevice)
        .filter(
            UnitDevice.unit_id == unit_id,
            UnitDevice.device_id == assignment.device_id,
        )
        .first()
    )

    if new_assignment:
        if new_assignment.unassigned_at is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="El dispositivo ya está asignado a esta unidad",
            )

        new_assignment.assigned_at = now
        new_assignment.unassigned_at = None
        db.add(new_assignment)
    else:
        new_assignment = UnitDevice(
            unit_id=unit_id,
            device_id=assignment.device_id,
            assigned_at=now,
        )
        db.add(new_assignment)

    # Actualizar estado del nuevo dispositivo
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

    db.refresh(new_assignment)

    return new_assignment


# ============================================
# Unit Profile Endpoints
# ============================================


@router.get("/{unit_id}/profile", response_model=UnitProfileComplete)
def get_unit_profile(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Obtiene el perfil completo de una unidad (unit_profile + vehicle_profile).

    Requiere: Acceso a la unidad (maestro o en user_units).

    El unit_profile siempre debe existir (se crea automáticamente con la unidad).
    Si por alguna razón no existe, lo crea como medida de seguridad.
    Si unit_type ≠ "vehicle", el campo "vehicle" viene como null.
    """
    # Verificar acceso a la unidad
    check_unit_access(db, unit_id, current_user)

    # Buscar o crear unit_profile (por seguridad, aunque debe existir siempre)
    unit_profile = db.query(UnitProfile).filter(UnitProfile.unit_id == unit_id).first()

    if not unit_profile:
        # Crear profile por defecto con unit_type "vehicle" (fallback de seguridad)
        unit_profile = UnitProfile(
            unit_id=unit_id,
            unit_type="vehicle",
        )
        db.add(unit_profile)
        db.commit()
        db.refresh(unit_profile)

    # Buscar vehicle_profile si es un vehículo
    vehicle_profile = None
    if unit_profile.unit_type == "vehicle":
        vehicle_profile = (
            db.query(VehicleProfile).filter(VehicleProfile.unit_id == unit_id).first()
        )

    # Construir respuesta
    response = UnitProfileComplete(
        unit_id=unit_profile.unit_id,
        unit_type=unit_profile.unit_type,
        icon_type=unit_profile.icon_type,
        description=unit_profile.description,
        brand=unit_profile.brand,
        model=unit_profile.model,
        color=unit_profile.color,
        year=unit_profile.year,
        vehicle=vehicle_profile,
    )

    return response


@router.patch("/{unit_id}/profile", response_model=UnitProfileComplete)
def update_unit_profile(
    unit_id: UUID,
    profile_update: UnitProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Actualiza el perfil de una unidad (unit_profile + vehicle_profile de forma unificada).

    Requiere:
    - Usuario maestro, o
    - Usuario con rol 'editor' o 'admin' en user_units

    Comportamiento:
    - Actualiza campos universales de unit_profile (icon_type, description, brand, model, color, year)
    - Si unit_type = "vehicle" y se envían campos de vehículo (plate, vin, fuel_type, passengers):
      * Si vehicle_profile NO existe → lo crea automáticamente (upsert)
      * Si vehicle_profile existe → lo actualiza
    - Ignora campos de vehículo si unit_type ≠ "vehicle"
    - Retorna el perfil completo unificado

    Body puede incluir cualquier combinación de campos:
    {
      "icon_type": "truck",
      "brand": "Ford",
      "model": "F-350",
      "color": "Rojo",
      "year": 2020,
      "plate": "ABC-123",
      "vin": "1FDUF3GT5GED12345",
      "fuel_type": "Diesel",
      "passengers": 5
    }
    """
    # Verificar acceso con rol editor o superior
    check_unit_access(db, unit_id, current_user, required_role="editor")

    # Buscar o crear unit_profile
    unit_profile = db.query(UnitProfile).filter(UnitProfile.unit_id == unit_id).first()

    if not unit_profile:
        # Crear profile por defecto (fallback de seguridad, aunque debe existir siempre)
        unit_profile = UnitProfile(
            unit_id=unit_id,
            unit_type="vehicle",
        )
        db.add(unit_profile)
        db.flush()

    # Obtener datos del body
    update_data = profile_update.model_dump(exclude_unset=True)

    # Separar campos de unit_profile y vehicle_profile
    unit_profile_fields = {
        "icon_type",
        "description",
        "brand",
        "model",
        "color",
        "year",
    }
    vehicle_profile_fields = {"plate", "vin", "fuel_type", "passengers"}

    # Actualizar campos de unit_profile
    for field in unit_profile_fields:
        if field in update_data:
            setattr(unit_profile, field, update_data[field])

    unit_profile.updated_at = datetime.utcnow()
    db.add(unit_profile)
    db.flush()

    # Manejar vehicle_profile si es un vehículo
    vehicle_profile = None
    if unit_profile.unit_type == "vehicle":
        # Verificar si hay campos de vehículo en el body
        vehicle_data = {
            field: update_data[field]
            for field in vehicle_profile_fields
            if field in update_data
        }

        if vehicle_data:
            # Buscar o crear vehicle_profile (upsert)
            vehicle_profile = (
                db.query(VehicleProfile)
                .filter(VehicleProfile.unit_id == unit_id)
                .first()
            )

            if vehicle_profile:
                # Actualizar existente
                for field, value in vehicle_data.items():
                    setattr(vehicle_profile, field, value)
                vehicle_profile.updated_at = datetime.utcnow()
            else:
                # Crear nuevo (upsert)
                vehicle_profile = VehicleProfile(
                    unit_id=unit_id,
                    plate=vehicle_data.get("plate"),
                    vin=vehicle_data.get("vin"),
                    fuel_type=vehicle_data.get("fuel_type"),
                    passengers=vehicle_data.get("passengers"),
                )

            db.add(vehicle_profile)
        else:
            # No hay campos de vehículo, solo buscar si existe
            vehicle_profile = (
                db.query(VehicleProfile)
                .filter(VehicleProfile.unit_id == unit_id)
                .first()
            )

    # Commit de todos los cambios
    db.commit()
    db.refresh(unit_profile)
    if vehicle_profile:
        db.refresh(vehicle_profile)

    # Construir respuesta
    response = UnitProfileComplete(
        unit_id=unit_profile.unit_id,
        unit_type=unit_profile.unit_type,
        icon_type=unit_profile.icon_type,
        description=unit_profile.description,
        brand=unit_profile.brand,
        model=unit_profile.model,
        color=unit_profile.color,
        year=unit_profile.year,
        vehicle=vehicle_profile,
    )

    return response


@router.post(
    "/{unit_id}/profile/vehicle",
    response_model=VehicleProfileOut,
    status_code=status.HTTP_201_CREATED,
)
def create_vehicle_profile(
    unit_id: UUID,
    vehicle_data: VehicleProfileCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Crea un perfil de vehículo (vehicle_profile) para una unidad.

    NOTA: Este endpoint se mantiene por compatibilidad.
    Se recomienda usar PATCH /units/{unit_id}/profile con campos de vehículo incluidos,
    que hace upsert automático.

    Requiere:
    - Usuario maestro, o
    - Usuario con rol 'editor' o 'admin' en user_units

    Validaciones:
    - El unit_profile debe existir y tener unit_type = "vehicle"
    - No debe existir ya un vehicle_profile para esta unidad
    """
    # Verificar acceso con rol editor o superior
    check_unit_access(db, unit_id, current_user, required_role="editor")

    # Verificar que existe unit_profile
    unit_profile = db.query(UnitProfile).filter(UnitProfile.unit_id == unit_id).first()

    if not unit_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El perfil de unidad no existe. Usa GET /units/{unit_id}/profile primero para crearlo.",
        )

    # Validar que sea un vehículo
    if unit_profile.unit_type != "vehicle":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El perfil de vehículo solo se puede crear para unidades de tipo 'vehicle' (tipo actual: {unit_profile.unit_type})",
        )

    # Verificar que no exista ya un vehicle_profile
    existing_vehicle = (
        db.query(VehicleProfile).filter(VehicleProfile.unit_id == unit_id).first()
    )

    if existing_vehicle:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ya existe un perfil de vehículo para esta unidad. Usa PATCH para actualizarlo.",
        )

    # Crear vehicle_profile
    vehicle_profile = VehicleProfile(
        unit_id=unit_id,
        plate=vehicle_data.plate,
        vin=vehicle_data.vin,
        fuel_type=vehicle_data.fuel_type,
        passengers=vehicle_data.passengers,
    )

    db.add(vehicle_profile)
    db.commit()
    db.refresh(vehicle_profile)

    return vehicle_profile


@router.patch("/{unit_id}/profile/vehicle", response_model=VehicleProfileOut)
def update_vehicle_profile(
    unit_id: UUID,
    vehicle_update: VehicleProfileUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Actualiza el perfil de vehículo (vehicle_profile) de una unidad.

    NOTA: Este endpoint se mantiene por compatibilidad.
    Se recomienda usar PATCH /units/{unit_id}/profile con campos de vehículo incluidos,
    que hace upsert automático.

    Requiere:
    - Usuario maestro, o
    - Usuario con rol 'editor' o 'admin' en user_units

    Validaciones:
    - El vehicle_profile debe existir (retorna 404 si no existe)
    """
    # Verificar acceso con rol editor o superior
    check_unit_access(db, unit_id, current_user, required_role="editor")

    # Buscar vehicle_profile
    vehicle_profile = (
        db.query(VehicleProfile).filter(VehicleProfile.unit_id == unit_id).first()
    )

    if not vehicle_profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El perfil de vehículo no existe. Usa POST /units/{unit_id}/profile/vehicle para crearlo.",
        )

    # Actualizar campos
    update_data = vehicle_update.model_dump(exclude_unset=True)

    for field, value in update_data.items():
        setattr(vehicle_profile, field, value)

    vehicle_profile.updated_at = datetime.utcnow()
    db.add(vehicle_profile)
    db.commit()
    db.refresh(vehicle_profile)

    return vehicle_profile


@router.get("/{unit_id}/users", response_model=List[UserUnitDetail])
def list_unit_users(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Lista los usuarios con acceso a una unidad específica.

    Requiere: Acceso a la unidad (maestro o en user_units).

    Retorna información detallada de cada usuario con acceso.
    """
    # Verificar acceso a la unidad
    unit = check_unit_access(db, unit_id, current_user)

    # Obtener asignaciones
    assignments = (
        db.query(UserUnit)
        .filter(UserUnit.unit_id == unit_id)
        .order_by(UserUnit.granted_at.desc())
        .all()
    )

    # Construir respuesta detallada
    result = []
    for assignment in assignments:
        user = db.query(User).filter(User.id == assignment.user_id).first()
        granted_by_user = None
        if assignment.granted_by:
            granted_by_user = (
                db.query(User).filter(User.id == assignment.granted_by).first()
            )

        detail = UserUnitDetail(
            id=assignment.id,
            user_id=assignment.user_id,
            unit_id=assignment.unit_id,
            granted_by=assignment.granted_by,
            granted_at=assignment.granted_at,
            role=assignment.role,
            user_email=user.email if user else None,
            user_full_name=user.full_name if user else None,
            unit_name=unit.name,
            granted_by_email=granted_by_user.email if granted_by_user else None,
        )
        result.append(detail)

    return result


@router.post("/{unit_id}/users", status_code=status.HTTP_201_CREATED)
def assign_user_to_unit(
    unit_id: UUID,
    assignment: UserUnitAssign,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Asigna un usuario a una unidad con un rol específico.

    Requiere: Usuario maestro del cliente.

    Body (JSON):
    {
        "user_id": "abc12345-e89b-12d3-a456-426614174000",
        "role": "editor"  // opcional, default: "viewer"
    }

    Roles disponibles: viewer, editor, admin
    """
    # Validar que sea maestro
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios maestros pueden asignar usuarios a unidades",
        )

    # Verificar que la unidad existe y pertenece al cliente
    unit = (
        db.query(Unit)
        .filter(
            Unit.id == unit_id,
            Unit.organization_id == current_user.organization_id,
            Unit.deleted_at.is_(None),
        )
        .first()
    )

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unidad no encontrada"
        )

    # Verificar que el usuario existe y pertenece a la organización
    target_user = (
        db.query(User)
        .filter(
            User.id == assignment.user_id,
            User.organization_id == current_user.organization_id,
        )
        .first()
    )

    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Usuario no encontrado o no pertenece a tu organización",
        )

    # No permitir asignar a usuarios maestros
    if target_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No es necesario asignar usuarios maestros (ya tienen acceso a todas las unidades)",
        )

    # Verificar que no existe una asignación previa
    existing = (
        db.query(UserUnit)
        .filter(UserUnit.user_id == assignment.user_id, UserUnit.unit_id == unit_id)
        .first()
    )

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El usuario ya tiene acceso a esta unidad con rol '{existing.role}'",
        )

    # Crear la asignación
    user_unit = UserUnit(
        user_id=assignment.user_id,
        unit_id=unit_id,
        role=assignment.role,
        granted_by=current_user.id,
    )
    db.add(user_unit)
    db.commit()
    db.refresh(user_unit)

    return {
        "message": "Usuario asignado exitosamente",
        "assignment_id": str(user_unit.id),
        "user_email": target_user.email,
        "unit_name": unit.name,
        "role": assignment.role,
    }


@router.delete("/{unit_id}/users/{user_id}", status_code=status.HTTP_200_OK)
def remove_user_from_unit(
    unit_id: UUID,
    user_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Revoca el acceso de un usuario a una unidad.

    Requiere: Usuario maestro del cliente.

    Elimina la asignación usuario→unidad.
    """
    # Validar que sea maestro
    if not current_user.is_master:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo los usuarios maestros pueden revocar accesos a unidades",
        )

    # Verificar que la unidad pertenece al cliente
    unit = (
        db.query(Unit)
        .filter(
            Unit.id == unit_id, Unit.organization_id == current_user.organization_id
        )
        .first()
    )

    if not unit:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unidad no encontrada"
        )

    # Buscar la asignación
    assignment = (
        db.query(UserUnit)
        .filter(UserUnit.user_id == user_id, UserUnit.unit_id == unit_id)
        .first()
    )

    if not assignment:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El usuario no tiene acceso a esta unidad",
        )

    # Obtener información para el mensaje
    user = db.query(User).filter(User.id == user_id).first()

    # Eliminar la asignación
    db.delete(assignment)
    db.commit()

    return {
        "message": "Acceso revocado exitosamente",
        "user_email": user.email if user else None,
        "unit_name": unit.name,
    }


@router.get("/{unit_id}/trips")
def get_unit_trips(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
    start_date: datetime = Query(
        ..., description="Fecha de inicio (ISO 8601, obligatorio)"
    ),
    end_date: datetime = Query(..., description="Fecha de fin (ISO 8601, obligatorio)"),
    limit: int = Query(50, ge=1, le=500, description="Límite de resultados"),
    cursor: Optional[datetime] = Query(
        None, description="Cursor de paginación (timestamp del último trip)"
    ),
    include_alerts: bool = Query(False, description="Incluir alertas en la respuesta"),
    include_points: bool = Query(
        False, description="Incluir puntos GPS en la respuesta"
    ),
    include_events: bool = Query(False, description="Incluir eventos en la respuesta"),
):
    """
    Obtiene los trips de una unidad específica en un rango de fechas.

    **IMPORTANTE:** Este endpoint requiere obligatoriamente `start_date` y `end_date`
    para optimizar las consultas en la base de datos Timescale.

    **Permisos:**
    - Usuario maestro: puede ver todos los trips de cualquier unidad del cliente
    - Usuario regular: solo trips de unidades asignadas en user_units

    **Filtros obligatorios:**
    - `start_date`: Fecha de inicio del rango (ISO 8601)
    - `end_date`: Fecha de fin del rango (ISO 8601)

    **Filtros opcionales:**
    - `limit`: Número máximo de resultados (default: 50, max: 500)
    - `cursor`: Timestamp del último trip recibido (para paginación)

    **Expansiones:**
    - `include_alerts`: Incluye las alertas de cada trip
    - `include_points`: Incluye los puntos GPS de cada trip
    - `include_events`: Incluye los eventos de cada trip

    **Nota:** Este endpoint devuelve trips de todos los dispositivos que han estado
    asignados a la unidad (tanto asignaciones activas como históricas).
    """
    from app.api.v1.endpoints.trips import build_trip_detail, build_trip_out
    from app.models.trip import Trip
    from app.schemas.trip import TripListResponse

    # Verificar acceso a la unidad
    check_unit_access(db, unit_id, current_user)

    # Obtener todos los dispositivos que han estado asignados a esta unidad
    unit_device_ids = (
        db.query(UnitDevice.device_id)
        .filter(UnitDevice.unit_id == unit_id)
        .distinct()
        .all()
    )
    unit_device_ids = [d[0] for d in unit_device_ids]

    if not unit_device_ids:
        return TripListResponse(
            trips=[], total=0, limit=limit, cursor=None, has_more=False
        )

    # Construir query con filtros obligatorios de fecha
    query = db.query(Trip).filter(
        Trip.device_id.in_(unit_device_ids),
        Trip.start_time >= start_date,
        Trip.start_time <= end_date,
    )

    # Aplicar cursor de paginación
    if cursor:
        query = query.filter(Trip.start_time < cursor)

    # Contar total
    total = query.count()

    # Ordenar y limitar
    trips = query.order_by(Trip.start_time.desc()).limit(limit + 1).all()

    # Determinar si hay más resultados
    has_more = len(trips) > limit
    if has_more:
        trips = trips[:limit]

    # Construir respuesta
    if include_alerts or include_points or include_events:
        trip_list = [
            build_trip_detail(
                db,
                trip,
                include_alerts=include_alerts,
                include_points=include_points,
                include_events=include_events,
            )
            for trip in trips
        ]
    else:
        trip_list = [build_trip_out(trip) for trip in trips]

    # Calcular nuevo cursor
    new_cursor = None
    if trips:
        new_cursor = trips[-1].start_time.isoformat()

    return TripListResponse(
        trips=trip_list,
        total=total,
        limit=limit,
        cursor=new_cursor if has_more else None,
        has_more=has_more,
    )


# ============================================
# Share Location Endpoints
# ============================================


@router.post(
    "/{unit_id}/share-location",
    response_model=ShareLocationResponse,
    status_code=status.HTTP_201_CREATED,
)
def share_unit_location(
    unit_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user_full),
):
    """
    Genera un token PASETO para compartir la ubicación de una unidad.

    **Funcionamiento:**
    - Verifica que el usuario tenga acceso a la unidad
    - Obtiene el device_id del dispositivo actualmente asignado
    - Genera un token PASETO v4.local con expiración de 30 minutos

    **Requiere:**
    - Acceso a la unidad (maestro o en user_units)
    - La unidad debe tener un dispositivo asignado activamente

    **Retorna:**
    - `token`: Token PASETO para compartir
    - `unit_id`: ID de la unidad
    - `device_id`: ID del dispositivo asignado
    - `expires_at`: Fecha y hora de expiración
    - `share_url`: URL para compartir (si FRONTEND_URL está configurado)
    """
    # Verificar acceso a la unidad
    check_unit_access(db, unit_id, current_user)

    # Obtener el dispositivo activo asignado a la unidad
    active_assignment = (
        db.query(UnitDevice)
        .filter(UnitDevice.unit_id == unit_id, UnitDevice.unassigned_at.is_(None))
        .first()
    )

    if not active_assignment:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La unidad no tiene un dispositivo asignado actualmente",
        )

    # Generar el token PASETO con el device_id
    token, expires_at = generate_location_share_token(
        unit_id=unit_id,
        device_id=active_assignment.device_id,
        expires_in_minutes=30,
    )

    # Construir URL de compartir si está configurado FRONTEND_URL
    share_url = None
    if settings.FRONTEND_URL:
        share_url = f"{settings.FRONTEND_URL}/share/{token}"

    return ShareLocationResponse(
        token=token,
        unit_id=unit_id,
        device_id=active_assignment.device_id,
        expires_at=expires_at,
        share_url=share_url,
    )
