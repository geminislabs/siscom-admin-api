from uuid import uuid4

from fastapi import status

from app.api.deps import get_mobility_kafka_producer
from app.main import app


class _FakeMobilityProducer:
    def __init__(self, should_publish: bool = True):
        self.should_publish = should_publish
        self.calls = []

    def publish_location(self, payload, key=None):
        self.calls.append({"payload": payload, "key": key})
        return self.should_publish


def test_publish_mobility_location_success(client):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(uuid4()),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
        "accuracy_m": 12.5,
        "speed_mps": 0.0,
        "heading": 180,
        "altitude_m": 1810,
        "battery_level": 82,
    }

    response = client.post("/api/v1/mobility/locations", json=payload)
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

    app.dependency_overrides.clear()


def test_publish_mobility_location_requires_required_fields(client):
    payload = {
        "device_id": str(uuid4()),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
    }

    response = client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_publish_mobility_location_returns_503_when_kafka_fails(client):
    fake_producer = _FakeMobilityProducer(should_publish=False)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(uuid4()),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
    }

    response = client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    app.dependency_overrides.clear()
