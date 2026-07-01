"""Tests para Teams, Members y Visibility Rules."""

from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_team_rules_kafka_producer
from app.main import app
from app.models.team import TeamVisibilityRule
from app.utils.datetime import utcnow


@pytest.fixture
def mock_kafka_producer():
    """Fixture que mockea el producer de Kafka."""
    mock_producer = MagicMock()
    mock_producer.publish_team_event.return_value = True

    def override():
        return mock_producer

    app.dependency_overrides[get_team_rules_kafka_producer] = override
    yield mock_producer
    app.dependency_overrides.pop(get_team_rules_kafka_producer, None)


def test_create_team(authenticated_client, test_organization_data, mock_kafka_producer):
    """Test crear un team crea el team y un miembro OWNER."""
    payload = {
        "name": "Mi Familia",
        "type": "FAMILY",
        "timezone": "America/Mexico_City",
    }
    response = authenticated_client.post("/api/v1/teams", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()["data"]
    assert data["name"] == "Mi Familia"
    assert data["type"] == "FAMILY"
    assert data["status"] == "ACTIVE"
    assert data["timezone"] == "America/Mexico_City"
    assert data["id"] is not None

    mock_kafka_producer.publish_team_event.assert_called()
    call_args = mock_kafka_producer.publish_team_event.call_args
    assert call_args[0][0]["event_type"] == "TEAM_CREATED"


def test_create_team_with_expires_at(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test crear un team con fecha de expiración."""
    future = (utcnow() + timedelta(days=30)).isoformat()
    payload = {
        "name": "Viaje Cancún",
        "type": "TRAVEL",
        "expires_at": future,
    }
    response = authenticated_client.post("/api/v1/teams", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()["data"]
    assert data["type"] == "TRAVEL"
    assert data["expires_at"] is not None


def test_create_team_validates_name(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test que name no puede estar vacío."""
    payload = {"name": "", "type": "FAMILY"}
    response = authenticated_client.post("/api/v1/teams", json=payload)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_create_team_generates_default_visibility_rules(
    authenticated_client, test_organization_data, db_session, mock_kafka_producer
):
    """Test que crear un team FAMILY genera reglas de visibilidad default."""
    payload = {"name": "Familia Test", "type": "FAMILY"}
    response = authenticated_client.post("/api/v1/teams", json=payload)
    assert response.status_code == status.HTTP_201_CREATED

    team_id = response.json()["data"]["id"]

    rules = (
        db_session.query(TeamVisibilityRule)
        .filter(TeamVisibilityRule.team_id == team_id)
        .all()
    )
    assert len(rules) >= 2


def test_list_teams_empty(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test listar teams cuando no hay ninguno."""
    response = authenticated_client.get("/api/v1/teams")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["data"] == []
    assert data["meta"]["total"] == 0


def test_list_teams_returns_user_teams(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test listar teams retorna los teams del usuario."""
    authenticated_client.post(
        "/api/v1/teams", json={"name": "Team 1", "type": "FAMILY"}
    )
    authenticated_client.post(
        "/api/v1/teams", json={"name": "Team 2", "type": "WORKFORCE"}
    )

    response = authenticated_client.get("/api/v1/teams")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["meta"]["total"] == 2
    assert len(data["data"]) == 2

    names = {t["name"] for t in data["data"]}
    assert "Team 1" in names
    assert "Team 2" in names


def test_list_teams_filter_by_status(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test filtrar teams por status."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Active Team", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    authenticated_client.post(f"/api/v1/teams/{team_id}/suspend")

    response = authenticated_client.get("/api/v1/teams?status=SUSPENDED")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["meta"]["total"] == 1
    assert data["data"][0]["status"] == "SUSPENDED"


def test_list_teams_filter_by_type(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test filtrar teams por tipo."""
    authenticated_client.post(
        "/api/v1/teams", json={"name": "Familia", "type": "FAMILY"}
    )
    authenticated_client.post(
        "/api/v1/teams", json={"name": "Trabajo", "type": "WORKFORCE"}
    )

    response = authenticated_client.get("/api/v1/teams?type=WORKFORCE")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["meta"]["total"] == 1
    assert data["data"][0]["type"] == "WORKFORCE"


def test_get_team(authenticated_client, test_organization_data, mock_kafka_producer):
    """Test obtener detalle de un team."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Mi Team", "type": "FRIENDS"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.get(f"/api/v1/teams/{team_id}")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert data["id"] == team_id
    assert data["name"] == "Mi Team"


def test_get_team_not_found(authenticated_client, mock_kafka_producer):
    """Test obtener team que no existe retorna 404."""
    fake_id = str(uuid4())
    response = authenticated_client.get(f"/api/v1/teams/{fake_id}")
    assert response.status_code == status.HTTP_404_NOT_FOUND


def test_update_team(authenticated_client, test_organization_data, mock_kafka_producer):
    """Test actualizar un team."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Original", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.patch(
        f"/api/v1/teams/{team_id}",
        json={"name": "Actualizado", "timezone": "America/Bogota"},
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert data["name"] == "Actualizado"
    assert data["timezone"] == "America/Bogota"

    mock_kafka_producer.publish_team_event.assert_called()


def test_suspend_team(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test suspender un team."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "A Suspender", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.post(f"/api/v1/teams/{team_id}/suspend")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert data["status"] == "SUSPENDED"


def test_suspend_team_already_suspended(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test suspender un team ya suspendido falla."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    authenticated_client.post(f"/api/v1/teams/{team_id}/suspend")
    response = authenticated_client.post(f"/api/v1/teams/{team_id}/suspend")
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_activate_team(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test reactivar un team suspendido."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    authenticated_client.post(f"/api/v1/teams/{team_id}/suspend")
    response = authenticated_client.post(f"/api/v1/teams/{team_id}/activate")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert data["status"] == "ACTIVE"


def test_delete_team(authenticated_client, test_organization_data, mock_kafka_producer):
    """Test eliminar un team (soft delete)."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "A Eliminar", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.delete(f"/api/v1/teams/{team_id}")
    assert response.status_code == status.HTTP_204_NO_CONTENT

    response = authenticated_client.get("/api/v1/teams")
    data = response.json()
    assert data["meta"]["total"] == 0

    response = authenticated_client.get("/api/v1/teams?include_deleted=true")
    data = response.json()
    assert data["meta"]["total"] == 1
    assert data["data"][0]["status"] == "DELETED"


def test_list_members(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test listar miembros de un team."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.get(f"/api/v1/teams/{team_id}/members")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert len(data) == 1
    assert data[0]["role"] == "OWNER"


def test_add_member(
    authenticated_client,
    test_organization_data,
    db_session,
    test_user_data,
    mock_kafka_producer,
):
    """Test agregar un miembro a un team."""
    from app.models.user import User

    new_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="new-user-sub",
        email="newuser@test.com",
        full_name="New User",
    )
    db_session.add(new_user)
    db_session.commit()
    db_session.refresh(new_user)

    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
    )
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()["data"]
    assert data["user_id"] == str(new_user.id)
    assert data["role"] == "MEMBER"


def test_add_member_duplicate_fails(
    authenticated_client,
    test_organization_data,
    db_session,
    test_user_data,
    mock_kafka_producer,
):
    """Test agregar el mismo usuario dos veces falla."""
    from app.models.user import User

    new_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="dup-user-sub",
        email="dup@test.com",
        full_name="Dup User",
    )
    db_session.add(new_user)
    db_session.commit()

    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    authenticated_client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
    )
    response = authenticated_client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
    )
    assert response.status_code == status.HTTP_409_CONFLICT


def test_update_member_role(
    authenticated_client,
    test_organization_data,
    db_session,
    test_user_data,
    mock_kafka_producer,
):
    """Test actualizar rol de un miembro."""
    from app.models.user import User

    new_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="role-user-sub",
        email="role@test.com",
        full_name="Role User",
    )
    db_session.add(new_user)
    db_session.commit()

    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    member_res = authenticated_client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
    )
    member_id = member_res.json()["data"]["id"]

    response = authenticated_client.patch(
        f"/api/v1/teams/{team_id}/members/{member_id}",
        json={"role": "ADMIN"},
    )
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert data["role"] == "ADMIN"


def test_cannot_demote_last_owner(
    authenticated_client, test_organization_data, db_session, mock_kafka_producer
):
    """Test que no se puede degradar al último OWNER."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    members_res = authenticated_client.get(f"/api/v1/teams/{team_id}/members")
    owner_member_id = members_res.json()["data"][0]["id"]

    response = authenticated_client.patch(
        f"/api/v1/teams/{team_id}/members/{owner_member_id}",
        json={"role": "ADMIN"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "último OWNER" in response.json()["detail"]


def test_remove_member(
    authenticated_client,
    test_organization_data,
    db_session,
    test_user_data,
    mock_kafka_producer,
):
    """Test remover un miembro de un team."""
    from app.models.user import User

    new_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="remove-user-sub",
        email="remove@test.com",
        full_name="Remove User",
    )
    db_session.add(new_user)
    db_session.commit()

    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    member_res = authenticated_client.post(
        f"/api/v1/teams/{team_id}/members",
        json={"user_id": str(new_user.id), "role": "MEMBER"},
    )
    member_id = member_res.json()["data"]["id"]

    response = authenticated_client.delete(
        f"/api/v1/teams/{team_id}/members/{member_id}"
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    members_res = authenticated_client.get(f"/api/v1/teams/{team_id}/members")
    assert len(members_res.json()["data"]) == 1


def test_cannot_remove_last_owner(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test que no se puede remover al último OWNER."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    members_res = authenticated_client.get(f"/api/v1/teams/{team_id}/members")
    owner_member_id = members_res.json()["data"][0]["id"]

    response = authenticated_client.delete(
        f"/api/v1/teams/{team_id}/members/{owner_member_id}"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "último OWNER" in response.json()["detail"]


def test_get_my_permissions(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test obtener permisos del usuario en un team."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.get(f"/api/v1/teams/{team_id}/me")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert data["role"] == "OWNER"
    assert data["permissions"]["can_manage_team"] is True
    assert data["permissions"]["can_delete_team"] is True


def test_list_visibility_rules(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test listar reglas de visibilidad de un team."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    response = authenticated_client.get(f"/api/v1/teams/{team_id}/visibility-rules")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()["data"]
    assert len(data) >= 2


def test_create_visibility_rule(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test crear una regla de visibilidad."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "FAMILY"}
    )
    team_id = res.json()["data"]["id"]

    payload = {
        "subject_role": "GUEST",
        "viewer_role": "ADMIN",
        "access_mode": "ON_DEMAND",
    }
    response = authenticated_client.post(
        f"/api/v1/teams/{team_id}/visibility-rules", json=payload
    )
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()["data"]
    assert data["subject_role"] == "GUEST"
    assert data["viewer_role"] == "ADMIN"
    assert data["access_mode"] == "ON_DEMAND"


def test_create_visibility_rule_scheduled_requires_schedule(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test que SCHEDULED requiere schedule."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "WORKFORCE"}
    )
    team_id = res.json()["data"]["id"]

    payload = {
        "subject_role": "EMPLOYEE",
        "viewer_role": "ADMIN",
        "access_mode": "SCHEDULED",
    }
    response = authenticated_client.post(
        f"/api/v1/teams/{team_id}/visibility-rules", json=payload
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_create_visibility_rule_with_schedule(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test crear regla SCHEDULED con schedule."""
    res = authenticated_client.post(
        "/api/v1/teams", json={"name": "Test", "type": "WORKFORCE"}
    )
    team_id = res.json()["data"]["id"]

    payload = {
        "subject_role": "EMPLOYEE",
        "viewer_role": "ADMIN",
        "access_mode": "SCHEDULED",
        "schedule": {
            "timezone": "America/Mexico_City",
            "windows": [
                {
                    "days": ["MON", "TUE", "WED", "THU", "FRI"],
                    "start": "08:00",
                    "end": "18:00",
                }
            ],
        },
    }
    response = authenticated_client.post(
        f"/api/v1/teams/{team_id}/visibility-rules", json=payload
    )
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()["data"]
    assert data["access_mode"] == "SCHEDULED"
    assert data["schedule"]["timezone"] == "America/Mexico_City"


def test_team_pagination(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    """Test paginación de teams."""
    for i in range(5):
        authenticated_client.post(
            "/api/v1/teams", json={"name": f"Team {i}", "type": "FAMILY"}
        )

    response = authenticated_client.get("/api/v1/teams?page=1&page_size=2")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert len(data["data"]) == 2
    assert data["meta"]["total"] == 5
    assert data["meta"]["page"] == 1
    assert data["meta"]["page_size"] == 2

    response = authenticated_client.get("/api/v1/teams?page=2&page_size=2")
    data = response.json()
    assert len(data["data"]) == 2
    assert data["meta"]["page"] == 2
