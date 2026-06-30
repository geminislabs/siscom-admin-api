"""Tests para Internal Snapshot Endpoints."""

from datetime import datetime, timezone

from fastapi import status

from app.models.team import EmergencyEvent, Team, TeamMember, TeamVisibilityRule


def test_get_team_snapshot_success(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team completo con miembros, reglas y eventos
    team = Team(
        account_id=test_account_data.id,
        name="Team Snapshot",
        type="FAMILY",
        status="ACTIVE",
        timezone="America/Mexico_City",
        created_by_user_id=test_user_data.id,
        team_metadata={"test": True},
    )
    db_session.add(team)
    db_session.flush()

    # Agregar miembro
    member = TeamMember(
        team_id=team.id,
        user_id=test_user_data.id,
        role="OWNER",
        joined_at=datetime.now(timezone.utc),
    )
    db_session.add(member)
    db_session.flush()

    # Agregar regla de visibilidad
    rule = TeamVisibilityRule(
        team_id=team.id,
        subject_role="MEMBER",
        viewer_role="OWNER",
        access_mode="ALWAYS",
        is_active=True,
        rule_metadata={},
    )
    db_session.add(rule)
    db_session.flush()

    # Agregar evento de emergencia activo
    event = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    db_session.add(event)
    db_session.commit()

    response = authenticated_client.get(f"/api/v1/internal/teams/{team.id}/snapshot")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]

    # Validar estructura del snapshot
    assert "team" in data
    assert "members" in data
    assert "visibility_rules" in data
    assert "active_emergency_events" in data

    # Validar team
    assert data["team"]["id"] == str(team.id)
    assert data["team"]["name"] == "Team Snapshot"
    assert data["team"]["status"] == "ACTIVE"

    # Validar miembros
    assert len(data["members"]) >= 1
    assert data["members"][0]["user_id"] == str(test_user_data.id)
    assert data["members"][0]["role"] == "OWNER"

    # Validar reglas
    assert len(data["visibility_rules"]) >= 1

    # Validar eventos activos
    assert len(data["active_emergency_events"]) >= 1
    assert data["active_emergency_events"][0]["emergency_type"] == "SOS"
    assert data["active_emergency_events"][0]["status"] == "ACTIVE"


def test_get_team_snapshot_only_active_rules(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Active Rules",
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

    # Regla activa
    rule_active = TeamVisibilityRule(
        team_id=team.id,
        subject_role="MEMBER",
        viewer_role="OWNER",
        access_mode="ALWAYS",
        is_active=True,
        rule_metadata={},
    )
    # Regla inactiva
    rule_inactive = TeamVisibilityRule(
        team_id=team.id,
        subject_role="MEMBER",
        viewer_role="ADMIN",
        access_mode="ALWAYS",
        is_active=False,
        rule_metadata={},
    )
    db_session.add_all([rule_active, rule_inactive])
    db_session.commit()

    response = authenticated_client.get(f"/api/v1/internal/teams/{team.id}/snapshot")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]

    # Solo debe incluir la regla activa
    assert len(data["visibility_rules"]) == 1
    assert data["visibility_rules"][0]["is_active"] is True


def test_get_team_snapshot_only_active_emergency_events(
    authenticated_client, db_session, test_user_data, test_account_data
):
    # Crear team
    team = Team(
        account_id=test_account_data.id,
        name="Team Active Events",
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

    # Evento activo
    event_active = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="SOS",
        status="ACTIVE",
        event_metadata={},
    )
    # Evento resuelto
    event_resolved = EmergencyEvent(
        team_id=team.id,
        triggered_by_user_id=test_user_data.id,
        emergency_type="PANIC",
        status="RESOLVED",
        ended_at=datetime.now(timezone.utc),
        event_metadata={},
    )
    db_session.add_all([event_active, event_resolved])
    db_session.commit()

    response = authenticated_client.get(f"/api/v1/internal/teams/{team.id}/snapshot")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()["data"]

    # Solo debe incluir el evento activo
    assert len(data["active_emergency_events"]) == 1
    assert data["active_emergency_events"][0]["status"] == "ACTIVE"
