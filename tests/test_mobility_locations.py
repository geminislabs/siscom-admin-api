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


def test_publish_mobility_location_accepts_h3_fields(client):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(uuid4()),
        "recorded_at": "2026-05-31T02:15:20Z",
        "lat": 20.593212,
        "lon": -100.392188,
        "h3_index": "8a2a1072b59ffff",
        "h3_resolution": 10,
    }

    response = client.post("/api/v1/mobility/locations", json=payload)
    assert response.status_code == status.HTTP_202_ACCEPTED

    data = response.json()
    assert data["h3_index"] == payload["h3_index"]
    assert data["h3_resolution"] == payload["h3_resolution"]
    assert fake_producer.calls[0]["payload"]["h3_index"] == payload["h3_index"]
    assert (
        fake_producer.calls[0]["payload"]["h3_resolution"] == payload["h3_resolution"]
    )

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


def test_publish_mobility_locations_batch_success(client):
    fake_producer = _FakeMobilityProducer(should_publish=True)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(uuid4()),
        "locations": [
            {
                "recorded_at": "2026-05-31T10:00:00Z",
                "lat": 20.593,
                "lon": -100.392,
                "accuracy_m": 12,
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

    response = client.post("/api/v1/mobility/locations/batch", json=payload)
    assert response.status_code == status.HTTP_202_ACCEPTED

    data = response.json()
    assert data["device_id"] == payload["device_id"]
    assert len(data["locations"]) == 2
    assert data["locations"][0]["recorded_at"] == payload["locations"][0]["recorded_at"]
    assert data["locations"][0]["h3_index"] == payload["locations"][0]["h3_index"]
    assert (
        data["locations"][0]["h3_resolution"]
        == payload["locations"][0]["h3_resolution"]
    )
    assert data["locations"][0]["received_at"].endswith("Z")

    assert len(fake_producer.calls) == 2
    assert fake_producer.calls[0]["key"] == payload["device_id"]
    assert fake_producer.calls[1]["key"] == payload["device_id"]

    app.dependency_overrides.clear()


def test_publish_mobility_locations_batch_requires_locations(client):
    payload = {
        "device_id": str(uuid4()),
        "locations": [],
    }

    response = client.post("/api/v1/mobility/locations/batch", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_publish_mobility_locations_batch_returns_503_when_kafka_fails(client):
    fake_producer = _FakeMobilityProducer(should_publish=False)
    app.dependency_overrides[get_mobility_kafka_producer] = lambda: fake_producer

    payload = {
        "device_id": str(uuid4()),
        "locations": [
            {
                "recorded_at": "2026-05-31T10:00:00Z",
                "lat": 20.593,
                "lon": -100.392,
            }
        ],
    }

    response = client.post("/api/v1/mobility/locations/batch", json=payload)
    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    app.dependency_overrides.clear()
