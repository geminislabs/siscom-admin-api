from uuid import uuid4

from fastapi import status

from app.api.v1.endpoints import user_commands as user_commands_endpoint
from app.models.command import Command
from app.models.device import Device
from app.models.unified_sim_profile import UnifiedSimProfile
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.services.kore import KoreAuthResponse, KoreSmsResponse


def test_user_command_requires_master(authenticated_client, test_user_data, db_session):
    test_user_data.is_master = False
    db_session.add(test_user_data)
    db_session.commit()

    payload = {
        "command_type": "ENGINE_RESUME",
        "unit_id": str(uuid4()),
    }

    response = authenticated_client.post("/api/v1/user-commands", json=payload)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "master" in response.json()["detail"].lower()


def test_engine_stop_requires_confirmation(authenticated_client):
    payload = {
        "command_type": "ENGINE_STOP",
        "unit_id": str(uuid4()),
    }

    response = authenticated_client.post("/api/v1/user-commands", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "requiere confirmation" in response.json()["detail"]


def test_user_command_returns_explicit_error_for_unsupported_device_model(
    authenticated_client, db_session, test_organization_data
):
    unit = Unit(
        id=uuid4(),
        organization_id=test_organization_data.id,
        name="Unidad Test",
        description="Unidad de prueba",
    )
    device = Device(
        device_id="353451234567890",
        brand="Queclink",
        model="GV300",
        status="asignado",
        organization_id=test_organization_data.id,
    )
    assignment = UnitDevice(unit_id=unit.id, device_id=device.device_id)

    db_session.add(unit)
    db_session.add(device)
    db_session.add(assignment)
    db_session.commit()

    payload = {
        "command_type": "ENGINE_RESUME",
        "unit_id": str(unit.id),
    }

    response = authenticated_client.post("/api/v1/user-commands", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "No se pudo formar el comando" in response.json()["detail"]


def test_engine_stop_creates_and_sends_command_via_kore(
    authenticated_client, db_session, test_organization_data, monkeypatch
):
    unit = Unit(
        id=uuid4(),
        organization_id=test_organization_data.id,
        name="Unidad Suntech",
        description="Unidad de prueba",
    )
    device = Device(
        device_id="353451234567891",
        brand="Suntech",
        model="ST4315U",
        status="asignado",
        organization_id=test_organization_data.id,
    )
    assignment = UnitDevice(unit_id=unit.id, device_id=device.device_id)
    sim_profile = UnifiedSimProfile(
        sim_id=uuid4(),
        device_id=device.device_id,
        carrier="KORE",
        iccid="8957000000000000000",
        msisdn=None,
        imsi=None,
        status="active",
        kore_sim_id="HS123456789",
    )

    db_session.add(unit)
    db_session.add(device)
    db_session.add(assignment)
    db_session.add(sim_profile)
    db_session.commit()

    monkeypatch.setattr(
        user_commands_endpoint,
        "_validate_user_password",
        lambda email, password: True,
    )
    monkeypatch.setattr(
        user_commands_endpoint.kore_service,
        "is_configured",
        lambda: True,
    )

    async def fake_authenticate():
        return KoreAuthResponse(
            access_token="fake-token",
            expires_in=3600,
            token_type="Bearer",
            scope="",
        )

    async def fake_send_sms_command(kore_sim_id: str, payload: str, access_token: str):
        return KoreSmsResponse(
            success=True,
            message="ok",
            response_data={"sid": "SM123", "status": "queued"},
        )

    monkeypatch.setattr(
        user_commands_endpoint.kore_service,
        "authenticate",
        fake_authenticate,
    )
    monkeypatch.setattr(
        user_commands_endpoint.kore_service,
        "send_sms_command",
        fake_send_sms_command,
    )

    payload = {
        "command_type": "ENGINE_STOP",
        "unit_id": str(unit.id),
        "confirmation": {
            "accepted_risk": True,
            "password": "any-password",
        },
    }

    response = authenticated_client.post("/api/v1/user-commands", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["status"] == "sent"

    command = db_session.query(Command).order_by(Command.requested_at.desc()).first()
    assert command is not None
    assert command.command == "AT^CMD;353451234567891;04;01"
    assert command.media == "KORE_SMS_API"
    assert command.status == "sent"
    assert command.command_metadata["command_type"] == "ENGINE_STOP"
    assert command.command_metadata["kore_sim_id"] == "HS123456789"


def test_engine_resume_accepts_suntech_st4330(
    authenticated_client, db_session, test_organization_data, monkeypatch
):
    unit = Unit(
        id=uuid4(),
        organization_id=test_organization_data.id,
        name="Unidad Suntech ST4330",
        description="Unidad de prueba",
    )
    device = Device(
        device_id="353451234567892",
        brand="Suntech",
        model="ST4330",
        status="asignado",
        organization_id=test_organization_data.id,
    )
    assignment = UnitDevice(unit_id=unit.id, device_id=device.device_id)
    sim_profile = UnifiedSimProfile(
        sim_id=uuid4(),
        device_id=device.device_id,
        carrier="KORE",
        iccid="8957000000000000001",
        msisdn=None,
        imsi=None,
        status="active",
        kore_sim_id="HS223456789",
    )

    db_session.add(unit)
    db_session.add(device)
    db_session.add(assignment)
    db_session.add(sim_profile)
    db_session.commit()

    monkeypatch.setattr(
        user_commands_endpoint.kore_service,
        "is_configured",
        lambda: True,
    )

    async def fake_authenticate():
        return KoreAuthResponse(
            access_token="fake-token",
            expires_in=3600,
            token_type="Bearer",
            scope="",
        )

    async def fake_send_sms_command(kore_sim_id: str, payload: str, access_token: str):
        return KoreSmsResponse(
            success=True,
            message="ok",
            response_data={"sid": "SM223", "status": "queued"},
        )

    monkeypatch.setattr(
        user_commands_endpoint.kore_service,
        "authenticate",
        fake_authenticate,
    )
    monkeypatch.setattr(
        user_commands_endpoint.kore_service,
        "send_sms_command",
        fake_send_sms_command,
    )

    payload = {
        "command_type": "ENGINE_RESUME",
        "unit_id": str(unit.id),
    }

    response = authenticated_client.post("/api/v1/user-commands", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    assert response.json()["status"] == "sent"

    command = db_session.query(Command).order_by(Command.requested_at.desc()).first()
    assert command is not None
    assert command.command == "AT^CMD;353451234567892;04;02"


def test_engine_resume_rejects_suntech_st449(
    authenticated_client, db_session, test_organization_data
):
    unit = Unit(
        id=uuid4(),
        organization_id=test_organization_data.id,
        name="Unidad Suntech ST449",
        description="Unidad de prueba",
    )
    device = Device(
        device_id="353451234567893",
        brand="Suntech",
        model="ST449",
        status="asignado",
        organization_id=test_organization_data.id,
    )
    assignment = UnitDevice(unit_id=unit.id, device_id=device.device_id)

    db_session.add(unit)
    db_session.add(device)
    db_session.add(assignment)
    db_session.commit()

    payload = {
        "command_type": "ENGINE_RESUME",
        "unit_id": str(unit.id),
    }

    response = authenticated_client.post("/api/v1/user-commands", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "No se pudo formar el comando" in response.json()["detail"]
