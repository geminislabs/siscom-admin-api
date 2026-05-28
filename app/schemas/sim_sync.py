from pydantic import BaseModel, Field


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
