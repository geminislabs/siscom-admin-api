"""`POST /organizations/{org}/users` — agregar un usuario existente a una
organización.

Hallazgo de la revisión del rediseño de `DELETE` (30/09/2026, sin relación
directa): aceptaba cualquier `users.id` del sistema sin comprobar que
perteneciera a la misma cuenta que la organización — mismo hueco que
`team_service.add_member` antes de su fix (PR #130). Cerrado aquí con el
mismo patrón: resolver la cuenta del usuario destino vía su organización, y
comparar contra `org.account_id`.
"""

from unittest.mock import patch
from uuid import uuid4

from fastapi import status

from app.models.account import Account
from app.models.organization import Organization
from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.user import User


def _agregar_usuario(client, actor, organizacion, user_id, rol="member"):
    """POST con la identidad del actor, entrando por donde entra producción.

    `require_organization_role` es una *factory*: no se puede sustituir con
    `dependency_overrides`, igual que en `test_estado_de_usuario_codigo.py`.
    """
    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": actor.cognito_sub}
    ):
        return client.post(
            f"/api/v1/organizations/{organizacion.id}/users",
            json={"user_id": str(user_id), "role": rol},
            headers={"Authorization": "Bearer lo-que-sea"},
        )


def _admin(db_session, organizacion, correo):
    user = User(
        id=uuid4(),
        organization_id=organizacion.id,
        cognito_sub=f"sub-{correo}",
        external_id=correo,
        email=correo,
        full_name="Admin",
        is_master=False,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=organizacion.id,
            user_id=user.id,
            role=OrganizationRole.ADMIN.value,
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user


def test_agregar_usuario_de_otra_cuenta_falla(db_session, client, test_account_data):
    """El hallazgo: sin esto, un admin podía agregar a cualquier persona del
    sistema, sin importar de qué cuenta fuera."""
    org = Organization(
        id=uuid4(),
        account_id=test_account_data.id,
        name="Mi organización",
        status="ACTIVE",
    )
    db_session.add(org)
    db_session.commit()
    admin = _admin(db_session, org, "admin@example.com")

    otra_cuenta = Account(id=uuid4(), name="Otra cuenta", status="ACTIVE")
    db_session.add(otra_cuenta)
    db_session.commit()
    otra_org = Organization(
        id=uuid4(),
        account_id=otra_cuenta.id,
        name="Organización ajena",
        status="ACTIVE",
    )
    db_session.add(otra_org)
    db_session.commit()
    outsider = User(
        id=uuid4(),
        organization_id=otra_org.id,
        cognito_sub="outsider-sub",
        email="outsider@otra-cuenta.com",
        full_name="Outsider",
    )
    db_session.add(outsider)
    db_session.commit()

    respuesta = _agregar_usuario(client, admin, org, outsider.id)

    assert respuesta.status_code == status.HTTP_404_NOT_FOUND
    assert (
        db_session.query(OrganizationUser)
        .filter(OrganizationUser.user_id == outsider.id)
        .first()
        is None
    )


def test_agregar_usuario_de_otra_organizacion_misma_cuenta_funciona(
    db_session, client, test_account_data
):
    """El límite es la cuenta, no la organización: agregar a alguien de otra
    organización de la misma cuenta sigue siendo el uso normal del endpoint."""
    org = Organization(
        id=uuid4(), account_id=test_account_data.id, name="Org destino", status="ACTIVE"
    )
    db_session.add(org)
    db_session.commit()
    admin = _admin(db_session, org, "admin2@example.com")

    otra_org_misma_cuenta = Organization(
        id=uuid4(), account_id=test_account_data.id, name="Org hermana", status="ACTIVE"
    )
    db_session.add(otra_org_misma_cuenta)
    db_session.commit()
    miembro = User(
        id=uuid4(),
        organization_id=otra_org_misma_cuenta.id,
        cognito_sub="hermana-sub",
        email="hermana@example.com",
        full_name="De la org hermana",
    )
    db_session.add(miembro)
    db_session.commit()

    respuesta = _agregar_usuario(client, admin, org, miembro.id)

    assert respuesta.status_code == status.HTTP_201_CREATED
    assert (
        db_session.query(OrganizationUser)
        .filter(
            OrganizationUser.user_id == miembro.id,
            OrganizationUser.organization_id == org.id,
        )
        .first()
        is not None
    )


def test_agregar_usuario_inexistente_sigue_dando_404(
    db_session, client, test_account_data
):
    org = Organization(
        id=uuid4(), account_id=test_account_data.id, name="Org", status="ACTIVE"
    )
    db_session.add(org)
    db_session.commit()
    admin = _admin(db_session, org, "admin3@example.com")

    respuesta = _agregar_usuario(client, admin, org, uuid4())

    assert respuesta.status_code == status.HTTP_404_NOT_FOUND
