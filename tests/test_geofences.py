from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_geofences_kafka_producer
from app.main import app
from app.models.geofence import Geofence, GeofenceCell
from app.models.organization import Organization


class _StubGeofencesKafkaProducer:
    def __init__(self):
        self.messages = []
        self.should_fail = False

    def publish_update(self, payload, key=None):
        self.messages.append({"payload": payload, "key": key})
        return not self.should_fail


@pytest.fixture(scope="function")
def geofences_kafka_stub_producer():
    stub = _StubGeofencesKafkaProducer()
    app.dependency_overrides[get_geofences_kafka_producer] = lambda: stub
    yield stub
    app.dependency_overrides.pop(get_geofences_kafka_producer, None)


def test_geofences_crud_soft_delete(
    authenticated_client, test_user_data, geofences_kafka_stub_producer
):
    create_payload = {
        "name": "Geocerca Centro",
        "description": "Zona principal",
        "config": {"color": "blue"},
        "h3_indexes": [600000000001, 600000000002, 600000000002],
    }

    create_response = authenticated_client.post(
        "/api/v1/geofences", json=create_payload
    )
    assert create_response.status_code == status.HTTP_201_CREATED

    created = create_response.json()
    geofence_id = created["id"]

    assert created["name"] == "Geocerca Centro"
    assert created["is_active"] is True
    assert created["h3_indexes"] == [600000000001, 600000000002]

    list_response = authenticated_client.get("/api/v1/geofences")
    assert list_response.status_code == status.HTTP_200_OK
    listed = list_response.json()
    assert any(item["id"] == geofence_id for item in listed)

    get_response = authenticated_client.get(f"/api/v1/geofences/{geofence_id}")
    assert get_response.status_code == status.HTTP_200_OK
    assert get_response.json()["id"] == geofence_id

    update_payload = {
        "name": "Geocerca Centro Actualizada",
        "description": "Nueva descripcion",
        "h3_indexes": [700000000001, 700000000001, 700000000003],
    }
    update_response = authenticated_client.patch(
        f"/api/v1/geofences/{geofence_id}", json=update_payload
    )
    assert update_response.status_code == status.HTTP_200_OK

    updated = update_response.json()
    assert updated["name"] == "Geocerca Centro Actualizada"
    assert updated["description"] == "Nueva descripcion"
    assert updated["h3_indexes"] == [700000000001, 700000000003]

    delete_response = authenticated_client.delete(f"/api/v1/geofences/{geofence_id}")
    assert delete_response.status_code == status.HTTP_200_OK
    assert delete_response.json()["is_active"] is False

    list_after_delete = authenticated_client.get("/api/v1/geofences")
    assert list_after_delete.status_code == status.HTTP_200_OK
    assert not any(item["id"] == geofence_id for item in list_after_delete.json())

    get_after_delete = authenticated_client.get(f"/api/v1/geofences/{geofence_id}")
    assert get_after_delete.status_code == status.HTTP_404_NOT_FOUND


def test_geofence_patch_replaces_all_h3_cells(
    authenticated_client,
    db_session,
    test_user_data,
    geofences_kafka_stub_producer,
):
    geofence = Geofence(
        id=uuid4(),
        organization_id=test_user_data.organization_id,
        created_by=test_user_data.id,
        name="Geocerca Test",
        description=None,
        config={"mode": "initial"},
        is_active=True,
    )
    db_session.add(geofence)
    db_session.commit()
    db_session.refresh(geofence)

    db_session.add(GeofenceCell(geofence_id=geofence.id, h3_index=800000000001))
    db_session.add(GeofenceCell(geofence_id=geofence.id, h3_index=800000000002))
    db_session.commit()

    patch_payload = {
        "config": {"mode": "replaced"},
        "h3_indexes": [900000000010, 900000000011],
    }

    response = authenticated_client.patch(
        f"/api/v1/geofences/{geofence.id}", json=patch_payload
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["config"] == {"mode": "replaced"}
    assert data["h3_indexes"] == [900000000010, 900000000011]

    cells = (
        db_session.query(GeofenceCell)
        .filter(GeofenceCell.geofence_id == geofence.id)
        .order_by(GeofenceCell.h3_index.asc())
        .all()
    )
    assert [cell.h3_index for cell in cells] == [900000000010, 900000000011]


def test_geofence_patch_with_empty_h3_list_clears_cells(
    authenticated_client,
    db_session,
    test_user_data,
    geofences_kafka_stub_producer,
):
    geofence = Geofence(
        id=uuid4(),
        organization_id=test_user_data.organization_id,
        created_by=test_user_data.id,
        name="Geocerca vaciable",
        description=None,
        config={},
        is_active=True,
    )
    db_session.add(geofence)
    db_session.commit()

    db_session.add(GeofenceCell(geofence_id=geofence.id, h3_index=810000000001))
    db_session.add(GeofenceCell(geofence_id=geofence.id, h3_index=810000000002))
    db_session.commit()

    response = authenticated_client.patch(
        f"/api/v1/geofences/{geofence.id}",
        json={"h3_indexes": []},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["h3_indexes"] == []

    count = (
        db_session.query(GeofenceCell)
        .filter(GeofenceCell.geofence_id == geofence.id)
        .count()
    )
    assert count == 0


def test_geofences_are_isolated_by_organization(
    authenticated_client,
    db_session,
    test_account_data,
    test_user_data,
    geofences_kafka_stub_producer,
):
    own_geofence = Geofence(
        id=uuid4(),
        organization_id=test_user_data.organization_id,
        created_by=test_user_data.id,
        name="Geocerca propia",
        description=None,
        config=None,
        is_active=True,
    )
    db_session.add(own_geofence)

    other_org = Organization(
        id=uuid4(),
        account_id=test_account_data.id,
        name="Otra Org",
        status="ACTIVE",
    )
    db_session.add(other_org)
    db_session.commit()

    foreign_geofence = Geofence(
        id=uuid4(),
        organization_id=other_org.id,
        created_by=test_user_data.id,
        name="Geocerca externa",
        description=None,
        config=None,
        is_active=True,
    )
    db_session.add(foreign_geofence)
    db_session.commit()

    list_response = authenticated_client.get("/api/v1/geofences")
    assert list_response.status_code == status.HTTP_200_OK

    ids = {item["id"] for item in list_response.json()}
    assert str(own_geofence.id) in ids
    assert str(foreign_geofence.id) not in ids

    get_foreign_response = authenticated_client.get(
        f"/api/v1/geofences/{foreign_geofence.id}"
    )
    assert get_foreign_response.status_code == status.HTTP_404_NOT_FOUND


def test_geofence_write_endpoints_publish_kafka_events(
    authenticated_client,
    geofences_kafka_stub_producer,
):
    create_response = authenticated_client.post(
        "/api/v1/geofences",
        json={
            "name": "Geocerca Kafka",
            "description": "",
            "config": {"color": "#2E86DE", "category": ""},
            "h3_indexes": [617733123123123123, 617733123123123124],
        },
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    created = create_response.json()
    geofence_id = created["id"]

    update_response = authenticated_client.patch(
        f"/api/v1/geofences/{geofence_id}",
        json={
            "name": "Geocerca Kafka Actualizada",
            "h3_indexes": [617733123123123125],
        },
    )
    assert update_response.status_code == status.HTTP_200_OK

    delete_response = authenticated_client.delete(f"/api/v1/geofences/{geofence_id}")
    assert delete_response.status_code == status.HTTP_200_OK

    events = geofences_kafka_stub_producer.messages
    assert len(events) == 3
    assert [event["payload"]["event_type"] for event in events] == [
        "UPSERT",
        "UPSERT",
        "DELETE",
    ]

    upsert_payload = events[0]["payload"]
    assert upsert_payload["entity"] == "geofence"
    assert upsert_payload["event_id"]
    assert upsert_payload["timestamp"].endswith("Z")
    assert upsert_payload["organization_id"] == created["organization_id"]
    assert upsert_payload["data"]["id"] == geofence_id
    assert upsert_payload["data"]["created_by"] == created["created_by"]
    assert upsert_payload["data"]["name"] == "Geocerca Kafka"
    assert upsert_payload["data"]["description"] == ""
    assert upsert_payload["data"]["is_active"] is True
    assert upsert_payload["data"]["config"] == {
        "color": "#2E86DE",
        "category": "",
    }
    assert upsert_payload["data"]["cells"] == [617733123123123123, 617733123123123124]
    assert upsert_payload["data"]["updated_at"].endswith("Z")

    delete_payload = events[-1]["payload"]
    assert delete_payload["event_type"] == "DELETE"
    assert delete_payload["entity"] == "geofence"
    assert delete_payload["data"] == {"id": geofence_id}


def test_geofence_kafka_error_does_not_break_persistence(
    authenticated_client,
    caplog,
    db_session,
    geofences_kafka_stub_producer,
):
    geofences_kafka_stub_producer.should_fail = True

    with caplog.at_level("ERROR"):
        response = authenticated_client.post(
            "/api/v1/geofences",
            json={
                "name": "Geocerca con error kafka",
                "description": "",
                "config": {"color": "#000000"},
                "h3_indexes": [700000000001],
            },
        )

    assert response.status_code == status.HTTP_201_CREATED
    created_id = response.json()["id"]

    persisted = db_session.query(Geofence).filter(Geofence.id == created_id).first()
    assert persisted is not None
    assert any(
        "Fallo publicando evento en Kafka" in rec.message for rec in caplog.records
    )
