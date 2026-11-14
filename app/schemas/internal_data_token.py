"""Data token de GAC para el plano de datos (`POST /internal/data-token`)."""

from datetime import datetime
from typing import List
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

# El mapa de GAC pide un dispositivo a la vez; el techo deja margen para una
# vista de varios sin convertir el endpoint en un volcado del inventario.
MAX_DISPOSITIVOS = 50


class GacDataTokenIn(BaseModel):
    device_ids: List[str] = Field(
        ...,
        min_length=1,
        max_length=MAX_DISPOSITIVOS,
        description="IMEIs de los dispositivos a leer",
    )

    @field_validator("device_ids")
    @classmethod
    def _sin_vacios_ni_repetidos(cls, valores: List[str]) -> List[str]:
        limpios = [v.strip() for v in valores]
        if any(not v for v in limpios):
            raise ValueError("device_ids no puede llevar valores vacíos")
        return list(dict.fromkeys(limpios))


class GacDataTokenDevice(BaseModel):
    device_id: str = Field(..., description="IMEI, como lo pidió GAC")
    device_ref: UUID = Field(
        ..., description="Referencia opaca con la que se pide a siscom-api"
    )


class GacDataTokenOut(BaseModel):
    """
    A diferencia del data token de Nexus, éste sí devuelve el alcance: GAC conoce
    los dispositivos por IMEI y siscom-api sólo acepta `device_ref`, así que sin
    la traducción el token no le sirve.
    """

    token: str = Field(..., description="Token PASETO v4.public para siscom-api")
    expires_at: datetime = Field(..., description="Instante de expiración (UTC)")
    expires_in: int = Field(..., description="Segundos de validez restantes")
    token_type: str = Field(default="Bearer", description="Tipo de token")
    devices: List[GacDataTokenDevice]
