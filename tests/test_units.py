"""Tests de endpoints de unidades."""

from uuid import UUID

from fastapi import status

from app.models.unit_device import UnitDevice
from app.models.unit_profile import UnitProfile
from app.models.vehicle_profile import VehicleProfile


def test_create_unit_minimal_creates_default_profile(authenticated_client, db_session):
    payload = {
        "name": "Unidad mínima",
        "description": "Solo campos base",
    }

    response = authenticated_client.post("/api/v1/units/", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["name"] == payload["name"]
    assert data["description"] == payload["description"]

    unit_id = UUID(data["id"])
    profile = db_session.query(UnitProfile).filter(UnitProfile.unit_id == unit_id).first()

    assert profile is not None
    assert profile.unit_type == "vehicle"
    assert profile.icon_type is None
    assert profile.brand is None
    assert profile.model is None
    assert profile.color is None
    assert profile.year is None


def test_create_unit_extended_camel_case_creates_profiles_and_device_assignment(
    authenticated_client, db_session, test_device_data, test_organization_data
):
    test_device_data.organization_id = test_organization_data.id
    test_device_data.status = "entregado"
    db_session.add(test_device_data)
    db_session.commit()

    payload = {
        "name": "Unidad full camel",
        "description": "Con perfil y dispositivo",
        "deviceId": test_device_data.device_id,
        "iconType": "vehicle-car-truck",
        "brand": "Ford",
        "model": "F-350",
        "color": "Rojo",
        "year": 2024,
        "plate": "ABC-123",
        "vin": "1FDUF3GT5GED12345",
    }

    response = authenticated_client.post("/api/v1/units/", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    unit_id = UUID(data["id"])

    profile = db_session.query(UnitProfile).filter(UnitProfile.unit_id == unit_id).first()
    assert profile is not None
    assert profile.icon_type == payload["iconType"]
    assert profile.brand == payload["brand"]
    assert profile.model == payload["model"]
    assert profile.color == payload["color"]
    assert profile.year == payload["year"]

    vehicle_profile = (
        db_session.query(VehicleProfile).filter(VehicleProfile.unit_id == unit_id).first()
    )
    assert vehicle_profile is not None
    assert vehicle_profile.plate == payload["plate"]
    assert vehicle_profile.vin == payload["vin"]

    assignment = (
        db_session.query(UnitDevice)
        .filter(UnitDevice.unit_id == unit_id, UnitDevice.unassigned_at.is_(None))
        .first()
    )
    assert assignment is not None
    assert assignment.device_id == payload["deviceId"]

    db_session.refresh(test_device_data)
    assert test_device_data.status == "asignado"
    assert test_device_data.last_assignment_at is not None


def test_create_unit_extended_snake_case_supported(authenticated_client, db_session):
    payload = {
        "name": "Unidad full snake",
        "description": "Con perfiles",
        "icon_type": "vehicle-car-sedan",
        "brand": "Toyota",
        "model": "Hilux",
        "color": "Blanco",
        "year": 2022,
        "plate": "XYZ-987",
        "vin": "1HGCM82633A123456",
    }

    response = authenticated_client.post("/api/v1/units/", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    unit_id = UUID(data["id"])

    profile = db_session.query(UnitProfile).filter(UnitProfile.unit_id == unit_id).first()
    assert profile is not None
    assert profile.icon_type == payload["icon_type"]
    assert profile.brand == payload["brand"]
    assert profile.model == payload["model"]
    assert profile.color == payload["color"]
    assert profile.year == payload["year"]

    vehicle_profile = (
        db_session.query(VehicleProfile).filter(VehicleProfile.unit_id == unit_id).first()
    )
    assert vehicle_profile is not None
    assert vehicle_profile.plate == payload["plate"]
    assert vehicle_profile.vin == payload["vin"]


def test_create_unit_with_invalid_device_returns_404(authenticated_client):
    payload = {
        "name": "Unidad con device inválido",
        "deviceId": "000000000000000",
    }

    response = authenticated_client.post("/api/v1/units/", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "Dispositivo no encontrado" in response.json()["detail"]
