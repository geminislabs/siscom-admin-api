from unittest.mock import AsyncMock, patch

from fastapi import status

from app.api.deps import AuthResult, get_auth_for_gac_admin
from app.main import app
from app.models.device import Device
from app.models.sim_card import SimCard
from app.models.sim_kore_profile import SimKoreProfile
from app.services.kore import KoreAuthError


def _override_gac_admin_auth():
    return AuthResult(
        auth_type="paseto",
        payload={"service": "gac", "role": "GAC_ADMIN"},
        service="gac",
        role="GAC_ADMIN",
    )


def test_sync_kore_sims_happy_path(client, db_session):
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    device_existing = Device(device_id="89883070000078034798", status="nuevo")
    db_session.add(device_existing)
    db_session.flush()

    sim_existing = SimCard(
        device_id=device_existing.device_id,
        iccid=device_existing.device_id,
        carrier="KORE",
        status="active",
    )
    db_session.add(sim_existing)
    db_session.flush()

    profile_existing = SimKoreProfile(
        sim_id=sim_existing.sim_id,
        kore_sim_id="HS_OLD",
        kore_account_id="AC_OLD",
    )
    db_session.add(profile_existing)
    db_session.commit()

    mocked_remote = [
        {
            "sid": "HS_UPDATED",
            "account_sid": "AC_UPDATED",
            "status": "new",
            "iccid": "89883070000078034798",
            "date_created": "2026-04-27T22:17:19Z",
            "date_updated": "2026-04-27T22:17:19Z",
            "url": "https://supersim.api.korewireless.com/v1/Sims/HS_UPDATED",
        },
        {
            "sid": "HS_CREATED",
            "account_sid": "AC_CREATED",
            "status": "ready",
            "iccid": "89883070000078030002",
            "date_created": "2026-04-27T22:17:19Z",
            "date_updated": "2026-04-27T22:17:19Z",
            "url": "https://supersim.api.korewireless.com/v1/Sims/HS_CREATED",
        },
        {
            "sid": "HS_NULL_DEVICE",
            "account_sid": "AC_NULL_DEVICE",
            "status": "new",
            "iccid": "89883070000078039999",
        },
        {
            "sid": None,
            "account_sid": "AC_INVALID",
            "status": "new",
            "iccid": "89883070000078038888",
        },
    ]

    with patch(
        "app.api.v1.endpoints.sims.kore_service.list_sims",
        AsyncMock(return_value=mocked_remote),
    ):
        response = client.post("/api/v1/sims/sync/kore")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    assert data["total_remote_sims"] == 4
    assert data["invalid_remote_records"] == 1
    assert data["matched_existing_sim_cards"] == 1
    assert data["sim_cards_created"] == 2
    assert data["sim_cards_updated"] == 1
    assert data["sim_cards_skipped_missing_device"] == 0
    assert data["kore_profiles_created"] == 2
    assert data["kore_profiles_updated"] == 1

    created_sim = (
        db_session.query(SimCard)
        .filter(SimCard.iccid == "89883070000078030002")
        .first()
    )
    assert created_sim is not None
    assert created_sim.status == "ready"

    created_profile = (
        db_session.query(SimKoreProfile)
        .filter(SimKoreProfile.sim_id == created_sim.sim_id)
        .first()
    )
    assert created_profile is not None
    assert created_profile.kore_sim_id == "HS_CREATED"

    updated_profile = (
        db_session.query(SimKoreProfile)
        .filter(SimKoreProfile.sim_id == sim_existing.sim_id)
        .first()
    )
    assert updated_profile.kore_sim_id == "HS_UPDATED"

    created_sim_without_device = (
        db_session.query(SimCard)
        .filter(SimCard.iccid == "89883070000078039999")
        .first()
    )
    assert created_sim_without_device is not None
    assert created_sim_without_device.device_id is None

    app.dependency_overrides.clear()


def test_sync_kore_sims_auth_error_returns_503(client):
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    with patch(
        "app.api.v1.endpoints.sims.kore_service.list_sims",
        AsyncMock(side_effect=KoreAuthError("bad auth")),
    ):
        response = client.post("/api/v1/sims/sync/kore")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    app.dependency_overrides.clear()
