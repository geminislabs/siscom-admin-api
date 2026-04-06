import json
from uuid import uuid4

from fastapi import status

from app.models.alert_rule import AlertRule, AlertRuleUnit
from app.models.organization import Organization
from app.models.unit import Unit


def _create_unit(db_session, organization_id, name):
    unit = Unit(
        id=uuid4(),
        organization_id=organization_id,
        name=name,
        description="Unidad de prueba",
    )
    db_session.add(unit)
    db_session.commit()
    db_session.refresh(unit)
    return unit


def test_alert_rules_crud_soft_delete(authenticated_client, db_session, test_user_data):
    unit_1 = _create_unit(db_session, test_user_data.organization_id, "Unidad 1")
    unit_2 = _create_unit(db_session, test_user_data.organization_id, "Unidad 2")

    create_payload = {
        "name": "Regla ignicion off",
        "type": "ignition_off",
        "config": {"event": "Engine OFF"},
        "unit_ids": [str(unit_1.id), str(unit_2.id)],
    }

    create_response = authenticated_client.post(
        "/api/v1/alert_rules", json=create_payload
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    created = create_response.json()
    assert created["name"] == "Regla ignicion off"
    assert created["is_active"] is True
    assert len(created["unit_ids"]) == 2

    rule_id = created["id"]

    list_response = authenticated_client.get("/api/v1/alert_rules")
    assert list_response.status_code == status.HTTP_200_OK
    listed = list_response.json()
    assert any(rule["id"] == rule_id for rule in listed)

    update_payload = {
        "name": "Regla ignicion off actualizada",
        "unit_ids": [str(unit_2.id)],
    }
    update_response = authenticated_client.patch(
        f"/api/v1/alert_rules/{rule_id}", json=update_payload
    )
    assert update_response.status_code == status.HTTP_200_OK
    updated = update_response.json()
    assert updated["name"] == "Regla ignicion off actualizada"
    assert updated["unit_ids"] == [str(unit_2.id)]

    delete_response = authenticated_client.delete(f"/api/v1/alert_rules/{rule_id}")
    assert delete_response.status_code == status.HTTP_200_OK
    deleted_data = delete_response.json()
    assert deleted_data["is_active"] is False

    list_after_delete_response = authenticated_client.get("/api/v1/alert_rules")
    assert list_after_delete_response.status_code == status.HTTP_200_OK
    after_delete = list_after_delete_response.json()
    assert not any(rule["id"] == rule_id for rule in after_delete)


def test_alert_rule_rejects_unit_from_other_organization(
    authenticated_client,
    db_session,
    test_account_data,
    test_organization_data,
    test_user_data,
):
    valid_unit = _create_unit(
        db_session, test_user_data.organization_id, "Unidad valida"
    )

    other_org = Organization(
        id=uuid4(),
        account_id=test_account_data.id,
        name="Otra org",
        status="ACTIVE",
    )
    db_session.add(other_org)
    db_session.commit()
    db_session.refresh(other_org)

    other_org_unit = _create_unit(db_session, other_org.id, "Unidad externa")

    payload = {
        "name": "Regla invalida",
        "type": "ignition_off",
        "config": {"event": "Engine OFF"},
        "unit_ids": [str(valid_unit.id), str(other_org_unit.id)],
    }

    response = authenticated_client.post("/api/v1/alert_rules", json=payload)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_alert_rules_hidden_when_organization_inactive(
    authenticated_client, db_session, test_user_data
):
    unit = _create_unit(db_session, test_user_data.organization_id, "Unidad 1")

    rule = AlertRule(
        organization_id=test_user_data.organization_id,
        created_by=test_user_data.id,
        name="Regla visible solo org activa",
        type="ignition_off",
        config={"event": "Engine OFF"},
        is_active=True,
    )
    db_session.add(rule)
    db_session.commit()
    db_session.refresh(rule)

    db_session.add(AlertRuleUnit(rule_id=rule.id, unit_id=unit.id))
    db_session.commit()

    org = (
        db_session.query(Organization)
        .filter(Organization.id == test_user_data.organization_id)
        .first()
    )
    org.status = "SUSPENDED"
    db_session.add(org)
    db_session.commit()

    response = authenticated_client.get("/api/v1/alert_rules")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == []


def test_create_alert_rule_without_units(authenticated_client):
    payload = {
        "name": "Regla sin unidades",
        "type": "ignition_off",
        "config": {"event": "Engine OFF"},
    }

    response = authenticated_client.post("/api/v1/alert_rules", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Regla sin unidades"
    assert data["unit_ids"] == []


def test_assign_and_unassign_units_for_rule(
    authenticated_client, db_session, test_user_data
):
    unit_1 = _create_unit(db_session, test_user_data.organization_id, "Unidad 1")
    unit_2 = _create_unit(db_session, test_user_data.organization_id, "Unidad 2")

    create_payload = {
        "name": "Regla asignable",
        "type": "ignition_off",
        "config": {"event": "Engine OFF"},
    }
    create_response = authenticated_client.post(
        "/api/v1/alert_rules", json=create_payload
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    rule_id = create_response.json()["id"]

    assign_payload = {"unit_ids": [str(unit_1.id), str(unit_2.id)]}
    assign_response = authenticated_client.post(
        f"/api/v1/alert_rules/{rule_id}/units", json=assign_payload
    )
    assert assign_response.status_code == status.HTTP_200_OK

    get_response = authenticated_client.get(f"/api/v1/alert_rules/{rule_id}")
    assert get_response.status_code == status.HTTP_200_OK
    unit_ids = set(get_response.json()["unit_ids"])
    assert unit_ids == {str(unit_1.id), str(unit_2.id)}

    unassign_payload = {"unit_ids": [str(unit_1.id)]}
    unassign_response = authenticated_client.delete(
        f"/api/v1/alert_rules/{rule_id}/units", json=unassign_payload
    )
    assert unassign_response.status_code == status.HTTP_200_OK

    get_after_unassign = authenticated_client.get(f"/api/v1/alert_rules/{rule_id}")
    assert get_after_unassign.status_code == status.HTTP_200_OK
    assert get_after_unassign.json()["unit_ids"] == [str(unit_2.id)]


def test_create_alert_rule_normalizes_config(authenticated_client):
    payload = {
        "name": "Regla config normalizada",
        "type": "ignition_off",
        "config": {
            "z": 1,
            "a": {
                "k2": None,
                "k1": "ok",
            },
            "m": [
                {"b": 2, "a": 1, "c": None},
                None,
            ],
            "n": None,
        },
    }

    response = authenticated_client.post("/api/v1/alert_rules", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    expected_config = {
        "a": {"k1": "ok"},
        "m": [{"a": 1, "b": 2}, None],
        "z": 1,
    }
    assert data["config"] == expected_config

    # Verifica orden determinista de llaves top-level y en objeto anidado.
    assert list(data["config"].keys()) == ["a", "m", "z"]
    assert list(data["config"]["a"].keys()) == ["k1"]


def test_update_alert_rule_normalizes_only_when_config_is_sent(
    authenticated_client,
    db_session,
    test_user_data,
):
    unit = _create_unit(db_session, test_user_data.organization_id, "Unidad update")
    create_payload = {
        "name": "Regla update config",
        "type": "ignition_off",
        "config": {"event": "Engine OFF", "threshold": {"max": 10, "min": 1}},
        "unit_ids": [str(unit.id)],
    }
    create_response = authenticated_client.post(
        "/api/v1/alert_rules", json=create_payload
    )
    assert create_response.status_code == status.HTTP_201_CREATED
    created = create_response.json()
    rule_id = created["id"]

    original_config = created["config"]

    patch_without_config = {
        "name": "Regla update config renombrada",
    }
    response_without_config = authenticated_client.patch(
        f"/api/v1/alert_rules/{rule_id}",
        json=patch_without_config,
    )
    assert response_without_config.status_code == status.HTTP_200_OK
    assert response_without_config.json()["config"] == original_config

    patch_with_config = {
        "config": {
            "z": "last",
            "a": {"drop": None, "keep": True},
            "list": [{"y": 2, "x": 1}],
            "to_remove": None,
        }
    }
    response_with_config = authenticated_client.patch(
        f"/api/v1/alert_rules/{rule_id}",
        json=patch_with_config,
    )
    assert response_with_config.status_code == status.HTTP_200_OK

    updated_config = response_with_config.json()["config"]
    assert updated_config == {
        "a": {"keep": True},
        "list": [{"x": 1, "y": 2}],
        "z": "last",
    }

    # Mantiene orden de listas, pero ordena claves de objetos internos.
    serialized = json.dumps(updated_config, ensure_ascii=False)
    assert (
        serialized == '{"a": {"keep": true}, "list": [{"x": 1, "y": 2}], "z": "last"}'
    )
