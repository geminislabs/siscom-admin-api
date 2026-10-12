from fastapi import status

from app.api.deps import AuthResult
from app.api.v1.endpoints.internal import accounts as accounts_endpoint
from app.main import app
from app.models.account_user import AccountRole, AccountUser


def test_list_all_accounts_returns_owner_email(
    authenticated_client, db_session, test_account_data, test_user_data, monkeypatch
):
    db_session.add(
        AccountUser(
            account_id=test_account_data.id,
            user_id=test_user_data.id,
            role=AccountRole.OWNER.value,
        )
    )
    db_session.commit()

    monkeypatch.setattr(
        accounts_endpoint,
        "get_accounts_nexus_status_map",
        lambda db, account_ids: {},
    )

    app.dependency_overrides[accounts_endpoint.get_auth_for_internal_accounts] = (
        lambda: AuthResult(
            auth_type="paseto",
            payload={"service": "gac", "role": "GAC_ADMIN"},
        )
    )

    response = authenticated_client.get("/api/v1/internal/accounts?limit=50")
    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert isinstance(body, list)
    assert any(
        row["id"] == str(test_account_data.id)
        and row["owner_email"] == test_user_data.email
        for row in body
    )


def test_get_account_by_id_dice_el_tipo_y_el_padre(
    client, db_session, test_account_data, monkeypatch
):
    """GAC decide si ofrece «convertir en marca» con esto (B4, rebanada 4)."""
    monkeypatch.setattr(
        accounts_endpoint, "get_account_nexus_status", lambda db, account_id: {}
    )
    app.dependency_overrides[accounts_endpoint.get_auth_for_internal_accounts] = (
        lambda: AuthResult(
            auth_type="paseto",
            payload={"service": "gac", "role": "GAC_ADMIN"},
        )
    )

    response = client.get(f"/api/v1/internal/accounts/{test_account_data.id}")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["account_type"] == "CUSTOMER"
    assert body["parent_account_id"] is None
