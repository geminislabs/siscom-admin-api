from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

# ============================================
# TripPoint Schemas
# ============================================


class TripPointOut(BaseModel):
    """Schema de salida para puntos GPS de un trip"""

    timestamp: datetime = Field(..., description="Timestamp del punto GPS")
    lat: float = Field(..., description="Latitud")
    lon: float = Field(..., description="Longitud (lng en la BD, lon en la API)")
    speed: Optional[float] = Field(None, description="Velocidad en el punto (km/h)")
    heading: Optional[float] = Field(None, description="Rumbo/dirección en grados")

    class Config:
        from_attributes = True
        # Mapeo de campo lng -> lon
        populate_by_name = True

    @classmethod
    def from_db(cls, point):
        """Método helper para convertir desde el modelo de DB"""
        return cls(
            timestamp=point.timestamp,
            lat=point.lat,
            lon=point.lng,  # Mapeo lng -> lon
            speed=point.speed,
            heading=point.heading,
        )


# ============================================
# TripAlert Schemas
# ============================================


class TripAlertOut(BaseModel):
    """Schema de salida para alertas de un trip"""

    timestamp: datetime = Field(..., description="Timestamp de la alerta")
    type: str = Field(..., description="Tipo de alerta")
    lat: Optional[float] = Field(None, description="Latitud de la alerta")
    lon: Optional[float] = Field(None, description="Longitud de la alerta")
    severity: Optional[int] = Field(
        None, description="Severidad de la alerta (1-5)", ge=1, le=5
    )

    class Config:
        from_attributes = True

    @classmethod
    def from_db(cls, alert):
        """Método helper para convertir desde el modelo de DB"""
        return cls(
            timestamp=alert.timestamp,
            type=alert.alert_type,
            lat=alert.lat,
            lon=alert.lon,
            severity=alert.severity,
        )


# ============================================
# TripEvent Schemas
# ============================================


class TripEventOut(BaseModel):
    """Schema de salida para eventos de un trip"""

    timestamp: datetime = Field(..., description="Timestamp del evento")
    event_type: str = Field(..., description="Tipo de evento")
    value: Optional[str] = Field(None, description="Valor del evento")

    class Config:
        from_attributes = True


# ============================================
# Trip Schemas
# ============================================


class TripBase(BaseModel):
    """Schema base para trip"""

    trip_id: UUID = Field(..., description="ID único del viaje")
    device_id: str = Field(..., description="ID del dispositivo que realizó el viaje")
    start_timestamp: datetime = Field(..., description="Timestamp de inicio del viaje")
    end_timestamp: Optional[datetime] = Field(
        None, description="Timestamp de fin del viaje; nulo si el viaje sigue abierto"
    )
    duration_minutes: Optional[float] = Field(
        None, description="Duración del viaje en minutos"
    )

    start_lat: Optional[float] = Field(None, description="Latitud de inicio")
    start_lon: Optional[float] = Field(None, description="Longitud de inicio")
    end_lat: Optional[float] = Field(None, description="Latitud de fin")
    end_lon: Optional[float] = Field(None, description="Longitud de fin")

    distance_km: Optional[float] = Field(
        None, description="Distancia recorrida en kilómetros"
    )

    class Config:
        from_attributes = True


class TripOut(TripBase):
    """Schema de salida para trip básico (sin expansiones)"""

    pass


class TripDetail(TripBase):
    """Schema de salida para trip con expansiones opcionales"""

    unit_id: Optional[UUID] = Field(
        None, description="ID de la unidad asignada al dispositivo"
    )
    unit_name: Optional[str] = Field(
        None, description="Nombre de la unidad asignada al dispositivo"
    )

    # Expansiones opcionales
    alerts: Optional[List[TripAlertOut]] = Field(
        None, description="Lista de alertas del viaje (solo si include_alerts=true)"
    )
    points: Optional[List[TripPointOut]] = Field(
        None, description="Lista de puntos GPS del viaje (solo si include_points=true)"
    )
    events: Optional[List[TripEventOut]] = Field(
        None, description="Lista de eventos del viaje (solo si include_events=true)"
    )

    class Config:
        from_attributes = True
        json_schema_extra = {
            "example": {
                "trip_id": "550e8400-e29b-41d4-a716-446655440000",
                "device_id": "864537040123456",
                "start_timestamp": "2025-11-29T08:00:00Z",
                "end_timestamp": "2025-11-29T09:30:00Z",
                "duration_minutes": 90.0,
                "start_lat": 19.4326,
                "start_lon": -99.1332,
                "end_lat": 19.4978,
                "end_lon": -99.1269,
                "distance_km": 12.5,
                "avg_speed": 45.3,
                "max_speed": 80.0,
                "alerts_count": 3,
                "points_count": 150,
                "events_count": 5,
                "unit_id": "abc12345-e89b-12d3-a456-426614174000",
                "unit_name": "Camión #45",
                "alerts": [
                    {
                        "timestamp": "2025-11-29T08:15:00Z",
                        "type": "speeding",
                        "lat": 19.4400,
                        "lon": -99.1300,
                        "severity": 2,
                    }
                ],
                "points": None,
                "events": None,
            }
        }


class TripListResponse(BaseModel):
    """Schema de respuesta para listado de trips con paginación"""

    trips: List[TripOut] = Field(..., description="Lista de viajes")
    total: int = Field(..., description="Total de viajes encontrados")
    limit: int = Field(..., description="Límite de resultados por página")
    cursor: Optional[str] = Field(
        None, description="Cursor para la siguiente página (timestamp del último trip)"
    )
    has_more: bool = Field(..., description="Indica si hay más resultados disponibles")

    class Config:
        json_schema_extra = {
            "example": {
                "trips": [
                    {
                        "trip_id": "550e8400-e29b-41d4-a716-446655440000",
                        "device_id": "864537040123456",
                        "start_timestamp": "2025-11-29T08:00:00Z",
                        "end_timestamp": "2025-11-29T09:30:00Z",
                        "duration_minutes": 90.0,
                        "start_lat": 19.4326,
                        "start_lon": -99.1332,
                        "end_lat": 19.4978,
                        "end_lon": -99.1269,
                        "distance_km": 12.5,
                        "avg_speed": 45.3,
                        "max_speed": 80.0,
                        "alerts_count": 3,
                        "points_count": 150,
                        "events_count": 5,
                    }
                ],
                "total": 1,
                "limit": 50,
                "cursor": "2025-11-29T08:00:00Z",
                "has_more": False,
            }
        }
