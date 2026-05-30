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


# ============================================
# Tests para GET /sims
# ============================================


def test_list_sims_returns_all(client, db_session):
    """Test que lista todas las SIMs."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    device = Device(device_id="DEV001", status="nuevo")
    db_session.add(device)
    db_session.flush()

    sim1 = SimCard(device_id="DEV001", iccid="89340001", carrier="KORE", status="active")
    sim2 = SimCard(device_id=None, iccid="89340002", carrier="KORE", status="active")
    db_session.add_all([sim1, sim2])
    db_session.commit()

    response = client.get("/api/v1/sims")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 2

    app.dependency_overrides.clear()


def test_list_sims_filter_unassigned(client, db_session):
    """Test que filtra SIMs sin dispositivo asignado."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    device = Device(device_id="DEV002", status="nuevo")
    db_session.add(device)
    db_session.flush()

    sim_assigned = SimCard(
        device_id="DEV002", iccid="89340003", carrier="KORE", status="active"
    )
    sim_unassigned = SimCard(
        device_id=None, iccid="89340004", carrier="KORE", status="active"
    )
    db_session.add_all([sim_assigned, sim_unassigned])
    db_session.commit()

    response = client.get("/api/v1/sims?unassigned=true")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data) == 1
    assert data[0]["iccid"] == "89340004"
    assert data[0]["device_id"] is None

    app.dependency_overrides.clear()


# ============================================
# Tests para GET /sims/{sim_id}
# ============================================


def test_get_sim_by_id(client, db_session):
    """Test que obtiene una SIM por ID."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    sim = SimCard(device_id=None, iccid="89340005", carrier="KORE", status="active")
    db_session.add(sim)
    db_session.flush()

    profile = SimKoreProfile(
        sim_id=sim.sim_id, kore_sim_id="HS123", kore_account_id="AC123"
    )
    db_session.add(profile)
    db_session.commit()

    response = client.get(f"/api/v1/sims/{sim.sim_id}")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["iccid"] == "89340005"
    assert data["kore_profile"]["kore_sim_id"] == "HS123"

    app.dependency_overrides.clear()


def test_get_sim_not_found(client):
    """Test que retorna 404 si la SIM no existe."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    response = client.get("/api/v1/sims/00000000-0000-0000-0000-000000000000")

    assert response.status_code == status.HTTP_404_NOT_FOUND

    app.dependency_overrides.clear()


# ============================================
# Tests para POST /sims/{sim_id}/assign
# ============================================


def test_assign_sim_to_device_success(client, db_session):
    """Test que asigna una SIM a un dispositivo exitosamente."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    device = Device(device_id="DEV003", status="nuevo")
    db_session.add(device)
    db_session.flush()

    sim = SimCard(device_id=None, iccid="89340006", carrier="KORE", status="active")
    db_session.add(sim)
    db_session.commit()

    response = client.post(
        f"/api/v1/sims/{sim.sim_id}/assign", json={"device_id": "DEV003"}
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["device_id"] == "DEV003"
    assert "asignada exitosamente" in data["message"]

    db_session.refresh(sim)
    assert sim.device_id == "DEV003"

    app.dependency_overrides.clear()


def test_assign_sim_already_assigned(client, db_session):
    """Test que falla si la SIM ya está asignada."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    device1 = Device(device_id="DEV004", status="nuevo")
    device2 = Device(device_id="DEV005", status="nuevo")
    db_session.add_all([device1, device2])
    db_session.flush()

    sim = SimCard(device_id="DEV004", iccid="89340007", carrier="KORE", status="active")
    db_session.add(sim)
    db_session.commit()

    response = client.post(
        f"/api/v1/sims/{sim.sim_id}/assign", json={"device_id": "DEV005"}
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "ya está asignada" in response.json()["detail"]

    app.dependency_overrides.clear()


def test_assign_sim_device_already_has_sim(client, db_session):
    """Test que falla si el dispositivo ya tiene una SIM."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    device = Device(device_id="DEV006", status="nuevo")
    db_session.add(device)
    db_session.flush()

    sim_existing = SimCard(
        device_id="DEV006", iccid="89340008", carrier="KORE", status="active"
    )
    sim_new = SimCard(device_id=None, iccid="89340009", carrier="KORE", status="active")
    db_session.add_all([sim_existing, sim_new])
    db_session.commit()

    response = client.post(
        f"/api/v1/sims/{sim_new.sim_id}/assign", json={"device_id": "DEV006"}
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "ya tiene una SIM asignada" in response.json()["detail"]

    app.dependency_overrides.clear()


def test_assign_sim_device_not_found(client, db_session):
    """Test que falla si el dispositivo no existe."""
    app.dependency_overrides[get_auth_for_gac_admin] = _override_gac_admin_auth

    sim = SimCard(device_id=None, iccid="89340010", carrier="KORE", status="active")
    db_session.add(sim)
    db_session.commit()

    response = client.post(
        f"/api/v1/sims/{sim.sim_id}/assign", json={"device_id": "NONEXISTENT"}
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Dispositivo no encontrado" in response.json()["detail"]

    app.dependency_overrides.clear()
