from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field


class SimKoreProfileOut(BaseModel):
    """Perfil KORE asociado a una SIM."""

    kore_sim_id: str
    kore_account_id: Optional[str] = None


class SimOut(BaseModel):
    """Representación de una SIM card."""

    sim_id: UUID
    device_id: Optional[str] = None
    carrier: str
    iccid: str
    imsi: Optional[str] = None
    msisdn: Optional[str] = None
    status: str
    kore_profile: Optional[SimKoreProfileOut] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SimAssignRequest(BaseModel):
    """Request para asignar una SIM a un dispositivo."""

    device_id: str = Field(..., description="ID del dispositivo al que asignar la SIM")


class SimAssignResponse(BaseModel):
    """Response de asignación de SIM."""

    sim_id: UUID
    device_id: str
    message: str


class SimKoreSyncResult(BaseModel):
    """Resultado de la sincronización de SIMs entre KORE y base local."""

    total_remote_sims: int = Field(..., description="SIMs obtenidas desde KORE")
    matched_existing_sim_cards: int = Field(
        ..., description="SIMs remotas que ya tenían sim_card local por ICCID"
    )
    sim_cards_created: int = Field(
        ..., description="Registros creados en sim_cards durante la sincronización"
    )
    sim_cards_updated: int = Field(
        ..., description="Registros actualizados en sim_cards (status/metadata/carrier)"
    )
    sim_cards_skipped_missing_device: int = Field(
        ...,
        description=(
            "SIMs remotas omitidas por incompatibilidad de datos (actualmente esperado: 0)"
        ),
    )
    kore_profiles_created: int = Field(
        ..., description="Registros creados en sim_kore_profiles"
    )
    kore_profiles_updated: int = Field(
        ..., description="Registros actualizados en sim_kore_profiles"
    )
    invalid_remote_records: int = Field(
        ..., description="Registros de KORE ignorados por falta de sid o iccid"
    )
