from datetime import datetime
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import AuthResult, get_auth_for_gac_admin
from app.db.session import get_db
from app.models.device import Device
from app.models.sim_card import SimCard
from app.models.sim_kore_profile import SimKoreProfile
from app.schemas.sim_sync import (
    SimAssignRequest,
    SimAssignResponse,
    SimKoreProfileOut,
    SimKoreSyncResult,
    SimOut,
)
from app.services.kore import KoreAuthError, KoreServiceError, kore_service

router = APIRouter()


def _build_sim_out(sim_card: SimCard, kore_profile: Optional[SimKoreProfile]) -> SimOut:
    """Construye un SimOut a partir de un SimCard y su perfil KORE opcional."""
    kore_profile_out = None
    if kore_profile:
        kore_profile_out = SimKoreProfileOut(
            kore_sim_id=kore_profile.kore_sim_id,
            kore_account_id=kore_profile.kore_account_id,
        )

    return SimOut(
        sim_id=sim_card.sim_id,
        device_id=sim_card.device_id,
        carrier=sim_card.carrier,
        iccid=sim_card.iccid,
        imsi=sim_card.imsi,
        msisdn=sim_card.msisdn,
        status=sim_card.status,
        kore_profile=kore_profile_out,
        created_at=sim_card.created_at,
        updated_at=sim_card.updated_at,
    )


@router.get("", response_model=List[SimOut])
def list_sims(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
    unassigned: Optional[bool] = Query(
        None, description="Filtrar SIMs sin dispositivo asignado"
    ),
    carrier: Optional[str] = Query(None, description="Filtrar por carrier (KORE, etc)"),
    status_filter: Optional[str] = Query(
        None, alias="status", description="Filtrar por status"
    ),
):
    """
    Lista todas las SIM cards.

    Filtros disponibles:
    - `unassigned=true`: Solo SIMs sin dispositivo asignado (device_id IS NULL)
    - `carrier`: Filtrar por proveedor (KORE, other)
    - `status`: Filtrar por estado (active, inactive, etc)
    """
    query = db.query(SimCard)

    if unassigned is True:
        query = query.filter(SimCard.device_id.is_(None))
    elif unassigned is False:
        query = query.filter(SimCard.device_id.isnot(None))

    if carrier:
        query = query.filter(SimCard.carrier == carrier)

    if status_filter:
        query = query.filter(SimCard.status == status_filter)

    sim_cards = query.order_by(SimCard.created_at.desc()).all()

    # Obtener perfiles KORE para las SIMs
    sim_ids = [sc.sim_id for sc in sim_cards]
    kore_profiles = (
        db.query(SimKoreProfile).filter(SimKoreProfile.sim_id.in_(sim_ids)).all()
        if sim_ids
        else []
    )
    profile_by_sim_id = {p.sim_id: p for p in kore_profiles}

    return [
        _build_sim_out(sim_card, profile_by_sim_id.get(sim_card.sim_id))
        for sim_card in sim_cards
    ]


@router.get("/{sim_id}", response_model=SimOut)
def get_sim(
    sim_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
):
    """Obtiene el detalle de una SIM específica."""
    sim_card = db.query(SimCard).filter(SimCard.sim_id == sim_id).first()

    if not sim_card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SIM no encontrada",
        )

    kore_profile = (
        db.query(SimKoreProfile).filter(SimKoreProfile.sim_id == sim_id).first()
    )

    return _build_sim_out(sim_card, kore_profile)


@router.post("/{sim_id}/assign", response_model=SimAssignResponse)
def assign_sim_to_device(
    sim_id: UUID,
    request: SimAssignRequest,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
):
    """
    Asigna una SIM existente a un dispositivo.

    Reglas:
    - La SIM debe existir y no tener dispositivo asignado actualmente.
    - El dispositivo debe existir y no tener otra SIM asignada.
    - Si el dispositivo ya tiene una SIM, se debe desasignar primero.
    """
    # Verificar que la SIM existe
    sim_card = db.query(SimCard).filter(SimCard.sim_id == sim_id).first()
    if not sim_card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SIM no encontrada",
        )

    # Verificar que la SIM no está asignada a otro dispositivo
    if sim_card.device_id is not None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La SIM ya está asignada al dispositivo {sim_card.device_id}",
        )

    # Verificar que el dispositivo existe
    device = db.query(Device).filter(Device.device_id == request.device_id).first()
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dispositivo no encontrado",
        )

    # Verificar que el dispositivo no tiene otra SIM asignada
    existing_sim = (
        db.query(SimCard).filter(SimCard.device_id == request.device_id).first()
    )
    if existing_sim:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"El dispositivo ya tiene una SIM asignada (ICCID: {existing_sim.iccid})",
        )

    # Asignar la SIM al dispositivo
    sim_card.device_id = request.device_id
    sim_card.updated_at = datetime.utcnow()

    db.commit()

    return SimAssignResponse(
        sim_id=sim_card.sim_id,
        device_id=request.device_id,
        message=f"SIM {sim_card.iccid} asignada exitosamente al dispositivo {request.device_id}",
    )


@router.post("/{sim_id}/unassign", response_model=SimAssignResponse)
def unassign_sim_from_device(
    sim_id: UUID,
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
):
    """
    Desasigna una SIM de su dispositivo actual.

    La SIM quedará disponible para ser asignada a otro dispositivo.
    """
    # Verificar que la SIM existe
    sim_card = db.query(SimCard).filter(SimCard.sim_id == sim_id).first()
    if not sim_card:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="SIM no encontrada",
        )

    # Verificar que la SIM está asignada
    if sim_card.device_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La SIM no está asignada a ningún dispositivo",
        )

    previous_device_id = sim_card.device_id
    sim_card.device_id = None
    sim_card.updated_at = datetime.utcnow()

    db.commit()

    return SimAssignResponse(
        sim_id=sim_card.sim_id,
        device_id=previous_device_id,
        message=f"SIM {sim_card.iccid} desasignada del dispositivo {previous_device_id}",
    )


@router.post("/sync/kore", response_model=SimKoreSyncResult)
async def sync_kore_sims(
    db: Session = Depends(get_db),
    auth: AuthResult = Depends(get_auth_for_gac_admin),
):
    """
    Sincroniza SIMs de KORE con las tablas locales:
    - Actualiza status/carrier/metadata en sim_cards.
    - Crea y actualiza sim_kore_profiles usando sid -> kore_sim_id.

    Reglas para sim_cards:
    - Se asocia por ICCID.
    - Si no existe sim_card, se crea aunque no exista device local compatible.
    - Cuando no hay match de dispositivo local, `device_id` se guarda como NULL.
    """
    try:
        remote_sims = await kore_service.list_sims(page_size=50)
    except KoreAuthError as e:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Error de autenticacion con KORE: {str(e)}",
        )
    except KoreServiceError as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error consultando KORE: {str(e)}",
        )

    total_remote = len(remote_sims)
    invalid_remote = 0
    matched_existing = 0
    sim_cards_created = 0
    sim_cards_updated = 0
    sim_cards_skipped_missing_device = 0
    kore_profiles_created = 0
    kore_profiles_updated = 0

    valid_sims: list[dict] = []
    iccids: set[str] = set()
    for sim in remote_sims:
        sid = sim.get("sid")
        iccid = sim.get("iccid")
        if not sid or not iccid:
            invalid_remote += 1
            continue
        valid_sims.append(sim)
        iccids.add(iccid)

    if not valid_sims:
        return SimKoreSyncResult(
            total_remote_sims=total_remote,
            matched_existing_sim_cards=0,
            sim_cards_created=0,
            sim_cards_updated=0,
            sim_cards_skipped_missing_device=0,
            kore_profiles_created=0,
            kore_profiles_updated=0,
            invalid_remote_records=invalid_remote,
        )

    existing_sim_cards = db.query(SimCard).filter(SimCard.iccid.in_(iccids)).all()
    sim_card_by_iccid = {sc.iccid: sc for sc in existing_sim_cards}

    if existing_sim_cards:
        sim_ids = [sim_card.sim_id for sim_card in existing_sim_cards]
        existing_profiles = (
            db.query(SimKoreProfile).filter(SimKoreProfile.sim_id.in_(sim_ids)).all()
        )
    else:
        existing_profiles = []
    profile_by_sim_id = {profile.sim_id: profile for profile in existing_profiles}

    for sim in valid_sims:
        sid = sim["sid"]
        iccid = sim["iccid"]
        account_sid = sim.get("account_sid")
        remote_status = sim.get("status")

        sim_card = sim_card_by_iccid.get(iccid)
        sim_card_created_now = False

        if sim_card:
            matched_existing += 1
        else:
            sim_card = SimCard(
                device_id=None,
                iccid=iccid,
                carrier="KORE",
                status=remote_status or "active",
                metadata_={
                    "kore": {
                        "sid": sid,
                        "account_sid": account_sid,
                        "date_created": sim.get("date_created"),
                        "date_updated": sim.get("date_updated"),
                        "url": sim.get("url"),
                    }
                },
            )
            db.add(sim_card)
            db.flush()
            sim_card_by_iccid[iccid] = sim_card
            sim_cards_created += 1
            sim_card_created_now = True

        updated_fields = False
        if sim_card.carrier != "KORE":
            sim_card.carrier = "KORE"
            updated_fields = True

        if remote_status and sim_card.status != remote_status:
            sim_card.status = remote_status
            updated_fields = True

        current_metadata = sim_card.metadata_ or {}
        target_kore_metadata = {
            "sid": sid,
            "account_sid": account_sid,
            "date_created": sim.get("date_created"),
            "date_updated": sim.get("date_updated"),
            "url": sim.get("url"),
        }
        if current_metadata.get("kore") != target_kore_metadata:
            current_metadata["kore"] = target_kore_metadata
            sim_card.metadata_ = current_metadata
            updated_fields = True

        if updated_fields:
            sim_card.updated_at = datetime.utcnow()
            if not sim_card_created_now:
                sim_cards_updated += 1

        kore_profile = profile_by_sim_id.get(sim_card.sim_id)
        if kore_profile:
            profile_changed = False
            if kore_profile.kore_sim_id != sid:
                kore_profile.kore_sim_id = sid
                profile_changed = True
            if kore_profile.kore_account_id != account_sid:
                kore_profile.kore_account_id = account_sid
                profile_changed = True
            if profile_changed:
                kore_profile.updated_at = datetime.utcnow()
                kore_profiles_updated += 1
        else:
            kore_profile = SimKoreProfile(
                sim_id=sim_card.sim_id,
                kore_sim_id=sid,
                kore_account_id=account_sid,
            )
            db.add(kore_profile)
            profile_by_sim_id[sim_card.sim_id] = kore_profile
            kore_profiles_created += 1

    db.commit()

    return SimKoreSyncResult(
        total_remote_sims=total_remote,
        matched_existing_sim_cards=matched_existing,
        sim_cards_created=sim_cards_created,
        sim_cards_updated=sim_cards_updated,
        sim_cards_skipped_missing_device=sim_cards_skipped_missing_device,
        kore_profiles_created=kore_profiles_created,
        kore_profiles_updated=kore_profiles_updated,
        invalid_remote_records=invalid_remote,
    )
