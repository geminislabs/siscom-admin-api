from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_mobility_kafka_producer
from app.main import app
from app.models.mobility_device import MobilityDevice
from app.models.user import User


class _FakeMobilityProducer:
    def __init__(self, should_publish: bool = True):
        self.should_publish = should_publish
        self.calls = []

    def publish_location(self, payload, key=None):
        self.calls.append({"payload": payload, "key": key})
        return self.should_publish


def _create_device(db_session, user_id, *, is_active: bool = True) -> MobilityDevice:
    device = MobilityDevice(
        id=uuid4(),
        user_id=user_id,
        device_type="PHONE",
        platform="ios",
        device_name="iPhone de prueba",
        is_active=is_active,
        mobility_metadata={},
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


@pytest.fixture
def own_device(db_session, test_user_data):
    """Dispositivo de movilidad activo del usuario autenticado."""
    return _create_device(db_session, test_user_data.id)


def test_publish_mobility_location_success(authenticated_client, own_device):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(own_device.id),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
        "accuracy_m": 12.5,
        "speed_mps": 0.0,
        "heading": 180,
        "altitude_m": 1810,
        "battery_level": 82,
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_202_ACCEPTED

    data = response.json()
    assert data["device_id"] == payload["device_id"]
    assert data["recorded_at"] == payload["recorded_at"]
    assert data["lat"] == payload["lat"]
    assert data["lon"] == payload["lon"]
    assert data["received_at"].endswith("Z")

    assert len(fake_producer.calls) == 1
    assert fake_producer.calls[0]["key"] == payload["device_id"]
    assert fake_producer.calls[0]["payload"]["received_at"].endswith("Z")


def test_publish_mobility_location_accepts_h3_fields(authenticated_client, own_device):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(own_device.id),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
        "h3_index": "8a2a1072b59ffff",
        "h3_resolution": 10,
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_202_ACCEPTED

    data = response.json()
    assert data["h3_index"] == payload["h3_index"]
    assert data["h3_resolution"] == payload["h3_resolution"]
    assert fake_producer.calls[0]["payload"]["h3_index"] == payload["h3_index"]
    assert (
        fake_producer.calls[0]["payload"]["h3_resolution"] == payload["h3_resolution"]
    )


def test_publish_mobility_location_accepts_motion_state(
    authenticated_client, own_device
):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(own_device.id),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
        "motion_state": "moving",
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_202_ACCEPTED

    data = response.json()
    assert data["motion_state"] == payload["motion_state"]
    assert fake_producer.calls[0]["payload"]["motion_state"] == payload["motion_state"]


def test_publish_mobility_location_requires_required_fields(
    authenticated_client, own_device
):
    payload = {
        "device_id": str(own_device.id),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_publish_mobility_location_returns_503_when_kafka_fails(
    authenticated_client, own_device
):
    fake_producer = _FakeMobilityProducer(should_publish=False)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(own_device.id),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_publish_mobility_location_rejects_unknown_device(
    authenticated_client, own_device
):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(uuid4()),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert fake_producer.calls == []


def test_publish_mobility_location_rejects_device_from_other_user(
    authenticated_client, db_session, test_organization_data
):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    other_user = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        cognito_sub="other-cognito-sub-mobility",
        email="other-mobility@example.com",
        full_name="Other User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()
    foreign_device = _create_device(db_session, other_user.id)

    payload = {
        "device_id": str(foreign_device.id),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert fake_producer.calls == []


def test_publish_mobility_location_rejects_inactive_device(
    authenticated_client, db_session, test_user_data
):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    inactive_device = _create_device(db_session, test_user_data.id, is_active=False)

    payload = {
        "device_id": str(inactive_device.id),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
    }

    response = authenticated_client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert fake_producer.calls == []


def test_publish_mobility_locations_batch_success(authenticated_client, own_device):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(own_device.id),
        "locations": [
            {
                "recorded_at": "2026-05-31T10:00:00Z",
                "lat": 20.593,
                "lon": -100.392,
                "accuracy_m": 12,
                "motion_state": "moving",
                "h3_index": "8a2a1072b59ffff",
                "h3_resolution": 10,
            },
            {
                "recorded_at": "2026-05-31T10:05:00Z",
                "lat": 20.594,
                "lon": -100.391,
                "accuracy_m": 10,
            },
        ],
    }

    response = authenticated_client.post(
        "/api/v1/mobility/locations/batch", json=payload
    )
    assert response.status_code == status.HTTP_202_ACCEPTED

    data = response.json()
    assert data["device_id"] == payload["device_id"]
    assert len(data["locations"]) == 2
    assert data["locations"][0]["recorded_at"] == payload["locations"][0]["recorded_at"]
    assert (
        data["locations"][0]["motion_state"] == payload["locations"][0]["motion_state"]
    )
    assert data["locations"][0]["h3_index"] == payload["locations"][0]["h3_index"]
    assert (
        data["locations"][0]["h3_resolution"]
        == payload["locations"][0]["h3_resolution"]
    )
    assert data["locations"][0]["received_at"].endswith("Z")

    assert len(fake_producer.calls) == 2
    assert fake_producer.calls[0]["key"] == payload["device_id"]
    assert fake_producer.calls[1]["key"] == payload["device_id"]


def test_publish_mobility_locations_batch_requires_locations(
    authenticated_client, own_device
):
    payload = {
        "device_id": str(own_device.id),
        "locations": [],
    }

    response = authenticated_client.post(
        "/api/v1/mobility/locations/batch", json=payload
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_publish_mobility_locations_batch_returns_503_when_kafka_fails(
    authenticated_client, own_device
):
    fake_producer = _FakeMobilityProducer(should_publish=False)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(own_device.id),
        "locations": [
            {
                "recorded_at": "2026-05-31T10:00:00Z",
                "lat": 20.593,
                "lon": -100.392,
            }
        ],
    }

    response = authenticated_client.post(
        "/api/v1/mobility/locations/batch", json=payload
    )
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


def test_publish_mobility_locations_batch_rejects_device_from_other_user(
    authenticated_client, db_session, test_organization_data
):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    other_user = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        cognito_sub="other-cognito-sub-mobility-batch",
        email="other-mobility-batch@example.com",
        full_name="Other User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()
    foreign_device = _create_device(db_session, other_user.id)

    payload = {
        "device_id": str(foreign_device.id),
        "locations": [
            {
                "recorded_at": "2026-05-31T10:00:00Z",
                "lat": 20.593,
                "lon": -100.392,
            }
        ],
    }

    response = authenticated_client.post(
        "/api/v1/mobility/locations/batch", json=payload
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert fake_producer.calls == []
