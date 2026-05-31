from uuid import UUID

from fastapi import status

from app.api.deps import get_user_devices_kafka_producer
from app.api.v1.endpoints import user_devices as user_devices_endpoint
from app.main import app


class _FakeUserDevicesProducer:
    def publish_update(self, payload, key=None):
        return True


def test_user_devices_register_returns_device_id(authenticated_client, monkeypatch):
    monkeypatch.setattr(
        user_devices_endpoint,
        "get_or_recreate_endpoint",
        lambda device_token, platform, endpoint_arn=None: ("arn:aws:sns:test", False),
    )

    app.dependency_overrides[get_user_devices_kafka_producer] = (
        lambda: _FakeUserDevicesProducer()
    )

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

    app.dependency_overrides.clear()
