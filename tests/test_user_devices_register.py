from uuid import UUID, uuid4

from fastapi import status

from app.api.deps import get_user_devices_kafka_producer
from app.api.v1.endpoints import user_devices as user_devices_endpoint
from app.main import app


class _CapturingUserDevicesProducer:
    def __init__(self):
        self.calls = []

    def publish_update(self, payload, key=None):
        self.calls.append((payload, key))
        return True


def test_user_devices_register_returns_device_id(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        user_devices_endpoint,
        "get_or_recreate_endpoint",
        lambda device_token, platform, endpoint_arn=None: ("arn:aws:sns:test", False),
    )

    producer = _CapturingUserDevicesProducer()
    app.dependency_overrides[get_user_devices_kafka_producer] = lambda: producer

    payload = {
        "device_token": "test-token-123",
        "platform": "ios",
    }

    response = authenticated_client.post("/api/v1/user-devices/register", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data.get("id") is not None
    UUID(data["id"])
    assert data["device_token"] == payload["device_token"]

    assert len(producer.calls) == 1
    kafka_payload, key = producer.calls[0]
    assert kafka_payload["entity"] == "user_device"
    assert kafka_payload["event_type"] == "UPSERT"
    assert kafka_payload["data"]["id"] == data["id"]
    assert kafka_payload["data"]["device_token"] == payload["device_token"]
    assert "unit_id" not in kafka_payload["data"]
    assert key == data["id"]

    app.dependency_overrides.clear()


def test_user_devices_register_desactiva_al_dueno_anterior(
    authenticated_client, monkeypatch, db_session, test_organization_data
):
    """En un aparato compartido, registrar el mismo device_token con otra
    cuenta desactiva la fila anterior -con su propio evento- en vez de
    reasignarla en silencio, que era el defecto que le apagaba el push a
    quien ya no es dueño de la sesión."""
    from app.models.user import User
    from app.models.user_device import UserDevice

    monkeypatch.setattr(
        user_devices_endpoint,
        "get_or_recreate_endpoint",
        lambda device_token, platform, endpoint_arn=None: ("arn:aws:sns:test", False),
    )

    producer = _CapturingUserDevicesProducer()
    app.dependency_overrides[get_user_devices_kafka_producer] = lambda: producer

    previous_user = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        cognito_sub="previous-owner-sub",
        email="previous@test.com",
        full_name="Previous Owner",
    )
    db_session.add(previous_user)
    db_session.commit()

    shared_token = "shared-device-token"
    previous_row = UserDevice(
        user_id=previous_user.id,
        device_token=shared_token,
        platform="android",
        is_active=True,
    )
    db_session.add(previous_row)
    db_session.commit()
    db_session.refresh(previous_row)

    payload = {"device_token": shared_token, "platform": "android"}
    response = authenticated_client.post("/api/v1/user-devices/register", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["id"] != str(previous_row.id)

    db_session.refresh(previous_row)
    assert previous_row.is_active is False
    assert previous_row.user_id == previous_user.id

    event_types = [call[0]["event_type"] for call in producer.calls]
    assert "DELETE" in event_types
    assert "UPSERT" in event_types

    delete_call = next(c for c in producer.calls if c[0]["event_type"] == "DELETE")
    assert delete_call[0]["data"]["id"] == str(previous_row.id)
    assert delete_call[0]["data"]["is_active"] is False

    app.dependency_overrides.clear()


def test_user_devices_register_mismo_usuario_reactiva_su_propia_fila(
    authenticated_client, monkeypatch, db_session, test_user_data
):
    """Si el propio usuario ya tenía una fila (inactiva) para ese token,
    la reactiva en vez de crear una duplicada."""
    from app.models.user_device import UserDevice

    monkeypatch.setattr(
        user_devices_endpoint,
        "get_or_recreate_endpoint",
        lambda device_token, platform, endpoint_arn=None: ("arn:aws:sns:test", False),
    )
    app.dependency_overrides[get_user_devices_kafka_producer] = (
        lambda: _CapturingUserDevicesProducer()
    )

    own_token = "own-old-token"
    own_row = UserDevice(
        user_id=test_user_data.id,
        device_token=own_token,
        platform="android",
        is_active=False,
    )
    db_session.add(own_row)
    db_session.commit()
    db_session.refresh(own_row)

    payload = {"device_token": own_token, "platform": "android"}
    response = authenticated_client.post("/api/v1/user-devices/register", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["id"] == str(own_row.id)
    assert data["is_active"] is True

    app.dependency_overrides.clear()
