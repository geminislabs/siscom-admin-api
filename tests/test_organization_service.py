"""Tests para app.services.organization.OrganizationService y helpers deprecados."""

from datetime import datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.user import User as UserModel
from app.services.organization import (
    OrganizationService,
    can_manage_billing,
    can_manage_billing_for_client,
    can_manage_users,
    can_manage_users_for_client,
    get_user_role,
    get_user_role_for_client,
)


@pytest.fixture
def org_id():
    return uuid4()


@pytest.fixture
def user_id():
    return uuid4()


def test_get_user_role_from_membership(org_id, user_id):
    session = MagicMock()
    membership = MagicMock()
    membership.role = OrganizationRole.ADMIN.value

    q = MagicMock()
    q.filter.return_value.first.return_value = membership
    session.query.return_value = q

    role = OrganizationService.get_user_role(session, user_id, org_id)
    assert role == OrganizationRole.ADMIN


def test_get_user_role_fallback_owner_when_master(org_id, user_id):
    session = MagicMock()

    user = MagicMock(spec=UserModel)
    user.organization_id = org_id
    user.is_master = True

    def query_side_effect(model):
        q = MagicMock()
        if model is OrganizationUser:
            q.filter.return_value.first.return_value = None
        elif model is UserModel:
            q.filter.return_value.first.return_value = user
        else:
            raise AssertionError(model)
        return q

    session.query.side_effect = query_side_effect

    role = OrganizationService.get_user_role(session, user_id, org_id)
    assert role == OrganizationRole.OWNER


def test_get_user_role_none_when_not_member(org_id, user_id):
    session = MagicMock()

    def query_side_effect(model):
        q = MagicMock()
        q.filter.return_value.first.return_value = None
        return q

    session.query.side_effect = query_side_effect

    assert OrganizationService.get_user_role(session, user_id, org_id) is None


def test_can_manage_users_requires_owner_or_admin(monkeypatch, org_id, user_id):
    monkeypatch.setattr(
        OrganizationService,
        "get_user_role",
        lambda db, uid, oid: OrganizationRole.MEMBER,
    )
    assert OrganizationService.can_manage_users(MagicMock(), user_id, org_id) is False

    monkeypatch.setattr(
        OrganizationService,
        "get_user_role",
        lambda db, uid, oid: OrganizationRole.OWNER,
    )
    assert OrganizationService.can_manage_users(MagicMock(), user_id, org_id) is True


def test_can_manage_billing_requires_owner_or_billing(monkeypatch, org_id, user_id):
    monkeypatch.setattr(
        OrganizationService,
        "get_user_role",
        lambda db, uid, oid: OrganizationRole.ADMIN,
    )
    assert OrganizationService.can_manage_billing(MagicMock(), user_id, org_id) is False

    monkeypatch.setattr(
        OrganizationService,
        "get_user_role",
        lambda db, uid, oid: OrganizationRole.BILLING,
    )
    assert OrganizationService.can_manage_billing(MagicMock(), user_id, org_id) is True


def test_add_member_raises_when_already_exists(org_id, user_id):
    session = MagicMock()
    existing = MagicMock()
    q = MagicMock()
    q.filter.return_value.first.return_value = existing
    session.query.return_value = q

    with pytest.raises(HTTPException) as ei:
        OrganizationService.add_member(session, org_id, user_id)
    assert ei.value.status_code == 400
    assert "ya es miembro" in ei.value.detail


def test_update_member_role_raises_when_actor_cannot_manage(monkeypatch, org_id):
    target = uuid4()
    actor = uuid4()

    monkeypatch.setattr(OrganizationService, "can_manage_users", lambda *a: False)

    with pytest.raises(HTTPException) as ei:
        OrganizationService.update_member_role(
            MagicMock(),
            org_id,
            target,
            OrganizationRole.MEMBER,
            actor,
        )
    assert ei.value.status_code == 403


def test_deprecated_helpers_delegate_to_organization_functions(user_id, org_id):
    db = MagicMock()

    with patch(
        "app.services.organization.get_user_role",
        return_value=OrganizationRole.MEMBER,
    ) as m1:
        assert get_user_role_for_client(db, user_id, org_id) == OrganizationRole.MEMBER
        m1.assert_called_once_with(db, user_id, org_id)

    with patch(
        "app.services.organization.can_manage_users",
        return_value=True,
    ) as m2:
        assert can_manage_users_for_client(db, user_id, org_id) is True
        m2.assert_called_once_with(db, user_id, org_id)

    with patch(
        "app.services.organization.can_manage_billing",
        return_value=False,
    ) as m3:
        assert can_manage_billing_for_client(db, user_id, org_id) is False
        m3.assert_called_once_with(db, user_id, org_id)


def test_module_level_shortcuts_match_service_methods(monkeypatch, org_id, user_id):
    monkeypatch.setattr(
        OrganizationService,
        "get_user_role",
        lambda db, uid, oid: OrganizationRole.ADMIN,
    )
    assert get_user_role(MagicMock(), user_id, org_id) == OrganizationRole.ADMIN


def test_get_organization_summary_raises_when_organization_missing(org_id):
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None

    with pytest.raises(HTTPException) as ei:
        OrganizationService.get_organization_summary(session, org_id)
    assert ei.value.status_code == 404


def test_get_organization_summary_returns_expected_keys(monkeypatch, org_id):
    org = MagicMock(spec=Organization)
    org.id = org_id
    org.account_id = uuid4()
    org.name = "Acme Org"
    org.status = "ACTIVE"
    org.billing_email = "bill@test.com"
    org.country = "MX"
    org.timezone = "America/Mexico_City"
    org.created_at = datetime(2026, 3, 1, 12, 0, 0)

    def query_side_effect(model):
        q = MagicMock()
        if model is Organization:
            q.filter.return_value.first.return_value = org
        elif model is OrganizationUser:
            q.filter.return_value.count.return_value = 7
        else:
            raise AssertionError(model)
        return q

    session = MagicMock()
    session.query.side_effect = query_side_effect

    monkeypatch.setattr(
        OrganizationService,
        "get_active_subscriptions",
        lambda db, oid_arg: [],
    )

    summary = OrganizationService.get_organization_summary(session, org_id)

    assert summary["organization"]["name"] == "Acme Org"
    assert summary["organization"]["id"] == str(org_id)
    assert summary["subscriptions"]["active_count"] == 0
    assert summary["members"]["count"] == 7
