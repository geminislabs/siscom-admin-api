"""Tests para Visibility Rules (completo) e Invites."""

from datetime import timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import status

from app.api.deps import get_current_user_full, get_team_rules_kafka_producer
from app.main import app
from app.models.team import TeamInvite, TeamMember, TeamVisibilityRule
from app.utils.datetime import utcnow


@pytest.fixture
def mock_kafka_producer():
    mock_producer = MagicMock()
    mock_producer.publish_team_event.return_value = True

    def override():
        return mock_producer

    app.dependency_overrides[get_team_rules_kafka_producer] = override
    yield mock_producer
    app.dependency_overrides.pop(get_team_rules_kafka_producer, None)


def _override_current_user(user):
    def _override():
        return user

    app.dependency_overrides[get_current_user_full] = _override


def _create_team(client) -> str:
    res = client.post("/api/v1/teams", json={"name": "Test Team", "type": "FAMILY"})
    assert res.status_code == status.HTTP_201_CREATED
    return res.json()["data"]["id"]


def _create_visibility_rule(client, team_id: str) -> str:
    res = client.post(
        f"/api/v1/teams/{team_id}/visibility-rules",
        json={
            "subject_role": "GUEST",
            "viewer_role": "ADMIN",
            "access_mode": "ON_DEMAND",
        },
    )
    assert res.status_code == status.HTTP_201_CREATED
    return res.json()["data"]["id"]


def _create_invite(client, team_id: str) -> dict:
    future = (utcnow() + timedelta(days=7)).isoformat()
    res = client.post(
        f"/api/v1/teams/{team_id}/invites",
        json={
            "invite_method": "LINK",
            "invited_role": "MEMBER",
            "expires_at": future,
            "max_uses": 1,
        },
    )
    assert res.status_code == status.HTTP_201_CREATED
    return res.json()["data"]


# --- Visibility Rules ---


def test_update_visibility_rule(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    rule_id = _create_visibility_rule(authenticated_client, team_id)

    res = authenticated_client.patch(
        f"/api/v1/teams/{team_id}/visibility-rules/{rule_id}",
        json={"access_mode": "ALWAYS", "schedule": None},
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["data"]["access_mode"] == "ALWAYS"


def test_update_visibility_rule_scheduled_requires_schedule(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    rule_id = _create_visibility_rule(authenticated_client, team_id)

    res = authenticated_client.patch(
        f"/api/v1/teams/{team_id}/visibility-rules/{rule_id}",
        json={"access_mode": "SCHEDULED"},
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_activate_visibility_rule(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    rule_id = _create_visibility_rule(authenticated_client, team_id)

    authenticated_client.patch(
        f"/api/v1/teams/{team_id}/visibility-rules/{rule_id}",
        json={"is_active": False},
    )

    res = authenticated_client.post(
        f"/api/v1/teams/{team_id}/visibility-rules/{rule_id}/activate"
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["data"]["is_active"] is True


def test_deactivate_visibility_rule(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    rule_id = _create_visibility_rule(authenticated_client, team_id)

    res = authenticated_client.post(
        f"/api/v1/teams/{team_id}/visibility-rules/{rule_id}/deactivate"
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["data"]["is_active"] is False


def test_delete_visibility_rule(
    authenticated_client,
    test_organization_data,
    db_session,
    mock_kafka_producer,
):
    team_id = _create_team(authenticated_client)
    rule_id = _create_visibility_rule(authenticated_client, team_id)

    res = authenticated_client.delete(
        f"/api/v1/teams/{team_id}/visibility-rules/{rule_id}"
    )
    assert res.status_code == status.HTTP_204_NO_CONTENT

    count = (
        db_session.query(TeamVisibilityRule)
        .filter(TeamVisibilityRule.id == rule_id)
        .count()
    )
    assert count == 0


# --- Invites ---


def test_create_invite_returns_token(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    data = _create_invite(authenticated_client, team_id)

    assert data["token"]
    assert data["invite_url"]
    assert data["invite_url"].endswith(data["token"])
    assert data["used_count"] == 0
    assert data["is_active"] is True


def test_list_invites_excludes_token(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    _create_invite(authenticated_client, team_id)

    res = authenticated_client.get(f"/api/v1/teams/{team_id}/invites")
    assert res.status_code == status.HTTP_200_OK

    items = res.json()["data"]
    assert len(items) == 1
    assert "token" not in items[0]
    assert "token_hash" not in items[0]


def test_revoke_invite(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    invite = _create_invite(authenticated_client, team_id)

    res = authenticated_client.post(
        f"/api/v1/teams/{team_id}/invites/{invite['id']}/revoke"
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["data"]["is_active"] is False


def test_get_public_invite_info(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    invite = _create_invite(authenticated_client, team_id)

    res = authenticated_client.get(f"/api/v1/invites/{invite['token']}")
    assert res.status_code == status.HTTP_200_OK

    data = res.json()["data"]
    assert data["team_id"] == team_id
    assert data["team_name"] == "Test Team"
    assert data["invited_role"] == "MEMBER"


def test_accept_invite_creates_member(
    authenticated_client,
    test_organization_data,
    db_session,
    test_user_data,
    mock_kafka_producer,
):
    from app.models.user import User

    team_id = _create_team(authenticated_client)
    invite = _create_invite(authenticated_client, team_id)

    new_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="invite-accept-sub",
        email="inviteaccept@test.com",
        full_name="Invite Accept User",
    )
    db_session.add(new_user)
    db_session.commit()

    _override_current_user(new_user)

    res = authenticated_client.post(f"/api/v1/invites/{invite['token']}/accept")
    assert res.status_code == status.HTTP_201_CREATED

    data = res.json()["data"]
    assert data["team_id"] == team_id
    assert data["role"] == "MEMBER"

    member = (
        db_session.query(TeamMember)
        .filter(
            TeamMember.team_id == team_id,
            TeamMember.user_id == new_user.id,
        )
        .first()
    )
    assert member is not None


def test_accept_invite_already_member(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    invite = _create_invite(authenticated_client, team_id)

    res = authenticated_client.post(f"/api/v1/invites/{invite['token']}/accept")
    assert res.status_code == status.HTTP_409_CONFLICT
    assert res.json()["detail"] == "ALREADY_MEMBER"


def test_accept_invite_invalid_token(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    res = authenticated_client.post("/api/v1/invites/invalid-token-xyz/accept")
    assert res.status_code == status.HTTP_404_NOT_FOUND


def test_accept_invite_expired(
    authenticated_client,
    test_organization_data,
    db_session,
    mock_kafka_producer,
):
    team_id = _create_team(authenticated_client)
    invite_data = _create_invite(authenticated_client, team_id)

    invite = (
        db_session.query(TeamInvite).filter(TeamInvite.id == invite_data["id"]).first()
    )
    invite.expires_at = utcnow() - timedelta(hours=1)
    db_session.commit()

    res = authenticated_client.post(f"/api/v1/invites/{invite_data['token']}/accept")
    assert res.status_code == status.HTTP_409_CONFLICT
    assert res.json()["detail"] == "INVITE_EXPIRED"


def test_accept_invite_after_revoke(
    authenticated_client,
    test_organization_data,
    db_session,
    test_user_data,
    mock_kafka_producer,
):
    from app.models.user import User

    team_id = _create_team(authenticated_client)
    invite = _create_invite(authenticated_client, team_id)

    authenticated_client.post(f"/api/v1/teams/{team_id}/invites/{invite['id']}/revoke")

    new_user = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="revoked-invite-sub",
        email="revokedinvite@test.com",
        full_name="Revoked Invite User",
    )
    db_session.add(new_user)
    db_session.commit()

    _override_current_user(new_user)

    res = authenticated_client.post(f"/api/v1/invites/{invite['token']}/accept")
    assert res.status_code == status.HTTP_409_CONFLICT


def test_create_invite_validates_expires_at(
    authenticated_client, test_organization_data, mock_kafka_producer
):
    team_id = _create_team(authenticated_client)
    past = (utcnow() - timedelta(days=1)).isoformat()

    res = authenticated_client.post(
        f"/api/v1/teams/{team_id}/invites",
        json={
            "invite_method": "LINK",
            "invited_role": "MEMBER",
            "expires_at": past,
            "max_uses": 1,
        },
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
