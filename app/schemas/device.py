from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

# ============================================
# Device Schemas
# ============================================

DeviceStatus = Literal[
    "nuevo", "preparado", "enviado", "entregado", "asignado", "devuelto", "inactivo"
]

CarrierType = Literal["KORE", "other"]


# ============================================
# SIM Profile Schemas
# ============================================


class SimKoreProfileInput(BaseModel):
    """Datos específicos para SIM KORE"""

    kore_sim_id: str = Field(
        ...,
        min_length=1,
        description="ID de SIM en KORE (ej: HS0ad6bc269850dfe13bc8bddfcf8399f4)",
    )
    kore_account_id: Optional[str] = Field(
        None, description="ID de cuenta KORE (opcional)"
    )


class SimKoreProfileOut(BaseModel):
    """Salida de perfil KORE"""

    kore_sim_id: str
    kore_account_id: Optional[str] = None

    class Config:
        from_attributes = True


class DeviceBase(BaseModel):
    """Schema base para dispositivos"""

    brand: Optional[str] = Field(
        None, max_length=100, description="Marca del dispositivo"
    )
    model: Optional[str] = Field(
        None, max_length=100, description="Modelo del dispositivo"
    )
    firmware_version: Optional[str] = Field(None, description="Versión de firmware")
    notes: Optional[str] = Field(None, description="Notas administrativas")


class DeviceCreate(BaseModel):
    """Schema para crear un nuevo dispositivo (admin/inventario)"""

    device_id: str = Field(
        ...,
        min_length=10,
        max_length=50,
        description="Identificador único del dispositivo (IMEI, serial, etc)",
    )
    brand: str = Field(
        ..., min_length=1, max_length=100, description="Marca del dispositivo"
    )
    model: str = Field(
        ..., min_length=1, max_length=100, description="Modelo del dispositivo"
    )
    firmware_version: Optional[str] = Field(None, description="Versión de firmware")
    notes: Optional[str] = Field(None, description="Notas administrativas")
    iccid: Optional[str] = Field(
        None,
        min_length=18,
        max_length=22,
        description="ICCID de la tarjeta SIM (opcional)",
    )
    carrier: Optional[CarrierType] = Field(
        "KORE",
        description="Proveedor de SIM (KORE, other). Default: KORE",
    )
    sim_profile: Optional[SimKoreProfileInput] = Field(
        None,
        description="Perfil específico de la SIM. Requerido si carrier=KORE y se quiere enviar comandos SMS",
    )

    @model_validator(mode="after")
    def validate_sim_profile(self):
        """Valida que sim_profile sea consistente con carrier"""
        if self.sim_profile and self.carrier != "KORE":
            raise ValueError("sim_profile solo es válido cuando carrier='KORE'")
        return self


class DeviceUpdate(BaseModel):
    """Schema para actualizar información básica del dispositivo"""

    organization_id: Optional[UUID] = Field(
        None,
        description="ID de la organización a la que se asigna el dispositivo",
    )
    status: Optional[DeviceStatus] = Field(
        None,
        description="Estado del dispositivo (nuevo, preparado, enviado, entregado, asignado, devuelto, inactivo)",
    )
    brand: Optional[str] = Field(None, max_length=100)
    model: Optional[str] = Field(None, max_length=100)
    firmware_version: Optional[str] = Field(None)
    notes: Optional[str] = Field(None)
    iccid: Optional[str] = Field(
        None,
        min_length=18,
        max_length=22,
        description="ICCID de la tarjeta SIM",
    )
    carrier: Optional[CarrierType] = Field(
        None,
        description="Proveedor de SIM (KORE, other)",
    )
    sim_profile: Optional[SimKoreProfileInput] = Field(
        None,
        description="Perfil específico de la SIM (para KORE)",
    )


class DeviceStatusUpdate(BaseModel):
    """Schema para actualizar el estado de un dispositivo"""

    new_status: DeviceStatus = Field(..., description="Nuevo estado del dispositivo")
    client_id: Optional[UUID] = Field(
        None, description="ID del cliente (requerido para 'preparado')"
    )
    unit_id: Optional[UUID] = Field(
        None, description="ID de la unidad (requerido para 'asignado')"
    )
    notes: Optional[str] = Field(None, description="Notas sobre el cambio de estado")


class DeviceOut(BaseModel):
    """Schema de salida para dispositivos"""

    # DEPRECATED: es el IMEI. Usar `device_ref` para direccionar el dispositivo.
    device_id: str
    device_ref: Optional[UUID] = None
    brand: Optional[str] = None
    model: Optional[str] = None
    firmware_version: Optional[str] = None
    client_id: Optional[UUID] = None
    status: str
    last_comm_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    last_assignment_at: Optional[datetime] = None
    notes: Optional[str] = None
    iccid: Optional[str] = Field(None, description="ICCID de la tarjeta SIM asignada")
    carrier: Optional[str] = Field(None, description="Proveedor de SIM")
    sim_profile: Optional[SimKoreProfileOut] = Field(
        None, description="Perfil de SIM (KORE)"
    )

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "device_id": "864537040123456",
                "device_ref": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
                "brand": "Suntech",
                "model": "ST300",
                "firmware_version": "1.0.17",
                "client_id": "d1e92a7a-bab3-4d87-8219-9cb8471a0c2b",
                "status": "asignado",
                "last_comm_at": "2025-01-15T10:30:00Z",
                "created_at": "2025-11-01T10:20:00Z",
                "updated_at": "2025-11-03T08:00:00Z",
                "last_assignment_at": "2025-11-03T08:00:00Z",
                "notes": "Instalado en unidad #45",
                "iccid": "89340123456789012345",
                "carrier": "KORE",
                "sim_profile": {
                    "kore_sim_id": "HS0ad6bc269850dfe13bc8bddfcf8399f4",
                    "kore_account_id": "CO1757099...",
                },
            }
        }


class DeviceWithProfileOut(DeviceOut):
    """Schema de salida para dispositivos con información del perfil de la unidad asignada"""

    # Información del perfil de la unidad (unit_profile)
    unit_id: Optional[UUID] = Field(None, description="ID de la unidad asignada")
    unit_name: Optional[str] = Field(None, description="Nombre de la unidad")
    profile_color: Optional[str] = Field(None, description="Color del vehículo/unidad")
    profile_icon_type: Optional[str] = Field(
        None, description="Tipo de ícono del vehículo/unidad"
    )
    profile_brand: Optional[str] = Field(None, description="Marca del vehículo/unidad")
    profile_model: Optional[str] = Field(None, description="Modelo del vehículo/unidad")
    profile_year: Optional[int] = Field(None, description="Año del vehículo/unidad")
    profile_serial: Optional[str] = Field(
        None, description="Número de serie del vehículo/unidad"
    )
    profile_description: Optional[str] = Field(
        None, description="Descripción del vehículo/unidad"
    )

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "device_id": "864537040123456",
                "device_ref": "1b9d6bcd-bbfd-4b2d-9b5d-ab8dfbbd4bed",
                "brand": "Suntech",
                "model": "ST300",
                "firmware_version": "1.0.17",
                "client_id": "d1e92a7a-bab3-4d87-8219-9cb8471a0c2b",
                "status": "asignado",
                "last_comm_at": "2025-01-15T10:30:00Z",
                "created_at": "2025-11-01T10:20:00Z",
                "updated_at": "2025-11-03T08:00:00Z",
                "last_assignment_at": "2025-11-03T08:00:00Z",
                "notes": "Instalado en unidad #45",
                "iccid": "89340123456789012345",
                "unit_id": "abc12345-e89b-12d3-a456-426614174000",
                "unit_name": "Camión #45",
                "profile_color": "Rojo",
                "profile_icon_type": "truck",
                "profile_brand": "Ford",
                "profile_model": "F-350",
                "profile_year": 2020,
                "profile_serial": "1FDUF3GT5GED12345",
                "profile_description": "Camión de carga pesada",
            }
        }


# ============================================
# DeviceEvent Schemas
# ============================================

EventType = Literal[
    "creado",
    "preparado",
    "enviado",
    "entregado",
    "asignado",
    "devuelto",
    "firmware_actualizado",
    "nota",
    "estado_cambiado",
]


class DeviceEventBase(BaseModel):
    """Schema base para eventos de dispositivos"""

    event_type: EventType
    event_details: Optional[str] = None


class DeviceEventCreate(DeviceEventBase):
    """Schema para crear un evento de dispositivo"""

    device_id: str = Field(..., description="ID del dispositivo")
    old_status: Optional[str] = None
    new_status: Optional[str] = None
    performed_by: Optional[UUID] = None


class UnitBase(BaseModel):
    name: str
    plate: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None


class UnitCreate(UnitBase):
    pass


class UnitOut(UnitBase):
    id: UUID
    client_id: UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "id": "323e4567-e89b-12d3-a456-426614174000",
                "client_id": "223e4567-e89b-12d3-a456-426614174000",
                "name": "Camión 01",
                "plate": "ABC-123-XY",
                "type": "Camión de carga",
                "description": "Camión para entregas locales",
                "created_at": "2024-01-10T08:00:00Z",
                "updated_at": "2024-01-10T08:00:00Z",
            }
        }
