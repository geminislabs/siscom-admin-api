"""Tests para Emergency Events."""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import status

from app.models.team import EmergencyEvent, Team, TeamMember
from app.models.user import User


def test_create_emergency_event_success(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Emergency Test",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    # Agregar usuario como miembro
    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.commit()

    payload = {
        "emergency_type": "SOS",
        "metadata": {
            "message": "Necesito ayuda",
            "location": {"lat": 20.5, "lon": -100.3},
        },
    }

    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events", json=payload
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()["data"]
    assert data["emergency_type"] == "SOS"
    assert data["status"] == "ACTIVE"
    assert data["team_id"] == str(team.id)
    assert data["triggered_by_user_id"] == str(test_user_data.id)
    assert data["metadata"]["message"] == "Necesito ayuda"


def test_create_emergency_event_team_not_active(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team inactivo
    team = Team(
        account_id=test_account_data.id,
        name="Team Inactive",
        type="FAMILY",
        status="SUSPENDED",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    # Agregar usuario como miembro
    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.commit()

    payload = {"emergency_type": "SOS", "metadata": {}}

    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events", json=payload
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "no está activo" in response.json()["detail"].lower()


def test_create_emergency_event_user_not_member(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team sin agregar al usuario como miembro
    team = Team(
        account_id=test_account_data.id,
        name="Team No Member",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.commit()

    payload = {"emergency_type": "SOS", "metadata": {}}

    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events", json=payload
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "miembro" in response.json()["detail"].lower()


def test_create_emergency_event_already_active(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Double Emergency",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    # Agregar usuario como miembro
    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.flush()

    # Crear evento activo previo
    existing_event = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    db_session.add(existing_event)
    db_session.commit()

    payload = {"emergency_type": "PANIC", "metadata": {}}

    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events", json=payload
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "ya tiene un evento" in response.json()["detail"].lower()


def test_list_emergency_events_success(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team List Events",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    # Agregar usuario como miembro
    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.flush()

    # Crear varios eventos
    event1 = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    event2 = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="MEDICAL",
        status="RESOLVED",
        ended_at=datetime.now(timezone.utc),
        event_metadata={},
    )
    db_session.add_all([event1, event2])
    db_session.commit()

    response = authenticated_client.get(f"/api/v1/teams/{team.id}/emergency-events")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data["data"]) == 2
    assert data["meta"]["total"] == 2


def test_list_emergency_events_filter_by_status(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Filter Events",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    # Agregar usuario como miembro
    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.flush()

    # Crear eventos con diferentes status
    event1 = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    event2 = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="PANIC",
        status="RESOLVED",
        ended_at=datetime.now(timezone.utc),
        event_metadata={},
    )
    db_session.add_all([event1, event2])
    db_session.commit()

    response = authenticated_client.get(
        f"/api/v1/teams/{team.id}/emergency-events?status=ACTIVE"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert len(data["data"]) == 1
    assert data["data"][0]["status"] == "ACTIVE"


def test_resolve_emergency_event_by_creator(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team y evento
    team = Team(
        account_id=test_account_data.id,
        name="Team Resolve",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="MEMBER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.flush()

    event = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    db_session.add(event)
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events/{event.id}/resolve"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["status"] == "RESOLVED"
    assert data["ended_at"] is not None


def test_resolve_emergency_event_by_admin(
    authenticated_client,
    db_session,
    test_user_data,
    test_account_data,
    test_organization_data,
):
    # Crear otro usuario
    other_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="other-resolve",
        email="other-resolve@test.com",
        full_name="Other User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()

    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Admin Resolve",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    # Usuario actual es ADMIN
    member_admin = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="ADMIN",
        joined_at=datetime.now(timezone.utc),
    )
    member_other = TeamMember(
        team_id=team.id,
        user_id=other_user.id,
        role="MEMBER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add_all([member_admin, member_other])
    db_session.flush()

    # Evento creado por otro usuario
    event = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=other_user.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    db_session.add(event)
    db_session.commit()

    # Usuario actual (ADMIN) puede resolver
    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events/{event.id}/resolve"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["status"] == "RESOLVED"


def test_resolve_emergency_event_forbidden(
    authenticated_client,
    db_session,
    test_user_data,
    test_account_data,
    test_organization_data,
):
    # Crear otro usuario
    other_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="other-forbidden",
        email="other-forbidden@test.com",
        full_name="Other User",
        is_master=False,
    )
    db_session.add(other_user)
    db_session.flush()

    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Forbidden Resolve",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    # Usuario actual es solo MEMBER
    member_current = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="MEMBER",
        joined_at=datetime.now(timezone.utc),
    )
    member_other = TeamMember(
        team_id=team.id,
        user_id=other_user.id,
        role="MEMBER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add_all([member_current, member_other])
    db_session.flush()

    # Evento creado por otro usuario
    event = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=other_user.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    db_session.add(event)
    db_session.commit()

    # Usuario actual no puede resolver (no es creator ni ADMIN/OWNER)
    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events/{event.id}/resolve"
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert "sin permisos" in response.json()["detail"].lower()


def test_resolve_emergency_event_not_active(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team y evento ya resuelto
    team = Team(
        account_id=test_account_data.id,
        name="Team Already Resolved",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.flush()

    event = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="RESOLVED",
        ended_at=datetime.now(timezone.utc),
        event_metadata={},
    )
    db_session.add(event)
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events/{event.id}/resolve"
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert "no está activo" in response.json()["detail"].lower()


def test_cancel_emergency_event_success(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team y evento
    team = Team(
        account_id=test_account_data.id,
        name="Team Cancel",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.flush()

    event = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    db_session.add(event)
    db_session.commit()

    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events/{event.id}/cancel"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]
    assert data["status"] == "CANCELLED"
    assert data["ended_at"] is not None


def test_cancel_emergency_event_not_found(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Not Found",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={},
    )
    db_session.add(team)
    db_session.flush()

    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.commit()

    fake_event_id = uuid4()
    response = authenticated_client.post(
        f"/api/v1/teams/{team.id}/emergency-events/{fake_event_id}/cancel"
    )
    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "no encontrado" in response.json()["detail"].lower()
