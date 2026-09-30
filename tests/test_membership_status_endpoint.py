"""`PATCH /organizations/{org}/users/{user_id}/status` — pausar/reactivar una
membresía sin borrarla y sin tocar `users.status`.

Es la mitad "contract" de la 034, y la que arregla el bug de fondo que tenía
`DELETE` para multi-org: hoy `DELETE` borra la membresía y, si la organización
coincide con `users.organization_id` (la columna heredada de una sola
organización), apaga la cuenta entera — así que alguien con dos membresías
podría quedar sin poder entrar a ninguna de las dos con solo sacarlo de una.

Este endpoint es una capacidad nueva y separada, no un reemplazo de `DELETE`:
sólo cambia `organization_users.status` de una fila puntual, nunca
`users.status` ni el proveedor de identidad. `DELETE` sigue intacto — ver
`tests/test_estado_de_usuario_codigo.py`.
"""

from unittest.mock import patch
from uuid import uuid4

from fastapi import status

from app.models.account_event import AccountEvent, EventType
from app.models.organization import Organization
from app.models.organization_user import (
    MembershipStatus,
    OrganizationRole,
    OrganizationUser,
)
from app.models.user import User, UserStatus


def _cambiar_estado(client, actor, organizacion, victima, nuevo_estado):
    """PATCH con la identidad del actor, entrando por donde entra producción.

    Mismo patrón que `_sacar_de_la_organizacion` en
    `test_estado_de_usuario_codigo.py`: `require_organization_role` es una
    *factory* y no se puede sustituir con `dependency_overrides`.
    """
    with patch(
        "app.api.deps.verify_cognito_token", return_value={"sub": actor.cognito_sub}
    ):
        return client.patch(
            f"/api/v1/organizations/{organizacion.id}/users/{victima.id}/status",
            json={"status": nuevo_estado},
            headers={"Authorization": "Bearer lo-que-sea"},
        )


def _otro_usuario(db_session, organizacion, correo, rol=OrganizationRole.MEMBER):
    user = User(
        id=uuid4(),
        organization_id=organizacion.id,
        cognito_sub=f"sub-{correo}",
        external_id=correo,
        email=correo,
        full_name="Quien Sea",
        is_master=False,
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        OrganizationUser(
            organization_id=organizacion.id, user_id=user.id, role=rol.value
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user


def _membresia_de(db_session, organizacion_id, user_id):
    return (
        db_session.query(OrganizationUser)
        .filter(
            OrganizationUser.organization_id == organizacion_id,
            OrganizationUser.user_id == user_id,
        )
        .first()
    )


# ── La pausa ─────────────────────────────────────────────────────────────


def test_pausar_pone_inactive_sin_borrar_la_fila(
    client, db_session, test_organization_data, test_user_data
):
    victima = _otro_usuario(db_session, test_organization_data, "pausa@example.com")

    respuesta = _cambiar_estado(
        client, test_user_data, test_organization_data, victima, "INACTIVE"
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json()["status"] == "INACTIVE"

    membresia = _membresia_de(db_session, test_organization_data.id, victima.id)
    assert membresia is not None, "la fila sigue ahi: PATCH no borra"
    assert membresia.status == MembershipStatus.INACTIVE.value


def test_pausar_no_toca_users_status_ni_el_rol(
    client, db_session, test_organization_data, test_user_data
):
    """La diferencia de fondo con `DELETE`: la cuenta global no se mueve."""
    victima = _otro_usuario(db_session, test_organization_data, "global@example.com")

    _cambiar_estado(client, test_user_data, test_organization_data, victima, "INACTIVE")

    db_session.refresh(victima)
    assert victima.status == UserStatus.ACTIVE.value

    membresia = _membresia_de(db_session, test_organization_data.id, victima.id)
    assert membresia.role == OrganizationRole.MEMBER.value


def test_reactivar_una_membresia_pausada(
    client, db_session, test_organization_data, test_user_data
):
    victima = _otro_usuario(db_session, test_organization_data, "vaivien@example.com")
    _cambiar_estado(client, test_user_data, test_organization_data, victima, "INACTIVE")

    respuesta = _cambiar_estado(
        client, test_user_data, test_organization_data, victima, "ACTIVE"
    )

    assert respuesta.status_code == status.HTTP_200_OK
    assert respuesta.json()["status"] == "ACTIVE"
    membresia = _membresia_de(db_session, test_organization_data.id, victima.id)
    assert membresia.status == MembershipStatus.ACTIVE.value


def test_pausar_una_membresia_no_afecta_la_otra_organizacion(
    client, db_session, test_organization_data, test_account_data, test_user_data
):
    """El punto entero del endpoint: alguien con dos membresías no pierde la
    otra por que le paguen una."""
    otra_org = Organization(
        id=uuid4(),
        name="Segunda Organizacion",
        status="ACTIVE",
        account_id=test_account_data.id,
    )
    db_session.add(otra_org)
    db_session.commit()

    victima = _otro_usuario(db_session, test_organization_data, "multi@example.com")
    db_session.add(
        OrganizationUser(
            organization_id=otra_org.id,
            user_id=victima.id,
            role=OrganizationRole.MEMBER.value,
        )
    )
    db_session.commit()

    _cambiar_estado(client, test_user_data, test_organization_data, victima, "INACTIVE")

    membresia_afectada = _membresia_de(
        db_session, test_organization_data.id, victima.id
    )
    membresia_intacta = _membresia_de(db_session, otra_org.id, victima.id)
    assert membresia_afectada.status == MembershipStatus.INACTIVE.value
    assert membresia_intacta.status == MembershipStatus.ACTIVE.value

    db_session.refresh(victima)
    assert victima.status == UserStatus.ACTIVE.value


# ── Permisos y salvaguardas ─────────────────────────────────────────────


def test_admin_no_puede_pausar_a_un_owner(
    client, db_session, test_organization_data, test_user_data
):
    """`test_user_data` ya es OWNER; se agrega un segundo owner y un admin que
    intenta tocarlo."""
    segundo_owner = _otro_usuario(
        db_session, test_organization_data, "owner2@example.com", OrganizationRole.OWNER
    )
    admin = _otro_usuario(
        db_session, test_organization_data, "admin@example.com", OrganizationRole.ADMIN
    )

    respuesta = _cambiar_estado(
        client, admin, test_organization_data, segundo_owner, "INACTIVE"
    )

    assert respuesta.status_code == status.HTTP_403_FORBIDDEN
    membresia = _membresia_de(db_session, test_organization_data.id, segundo_owner.id)
    assert membresia.status == MembershipStatus.ACTIVE.value


def test_no_se_puede_inactivar_al_ultimo_owner_activo(
    client, db_session, test_organization_data, test_user_data
):
    """`test_user_data` es el único owner de `test_organization_data`."""
    respuesta = _cambiar_estado(
        client, test_user_data, test_organization_data, test_user_data, "INACTIVE"
    )

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST
    membresia = _membresia_de(db_session, test_organization_data.id, test_user_data.id)
    assert membresia.status == MembershipStatus.ACTIVE.value


def test_un_segundo_owner_activo_si_permite_inactivar_al_primero(
    client, db_session, test_organization_data, test_user_data
):
    """El conteo de `_count_owners` es sobre owners **activos** — con dos, sí
    se puede pausar a uno."""
    segundo_owner = _otro_usuario(
        db_session, test_organization_data, "owner2@example.com", OrganizationRole.OWNER
    )

    respuesta = _cambiar_estado(
        client, segundo_owner, test_organization_data, test_user_data, "INACTIVE"
    )

    assert respuesta.status_code == status.HTTP_200_OK
    membresia = _membresia_de(db_session, test_organization_data.id, test_user_data.id)
    assert membresia.status == MembershipStatus.INACTIVE.value


def test_un_owner_pausado_no_cuenta_como_red_de_seguridad(
    client, db_session, test_organization_data, test_user_data
):
    """Pausar al owner A no debe permitir vaciar también al owner B con la
    excusa de que "hay dos": A ya no cuenta."""
    segundo_owner = _otro_usuario(
        db_session, test_organization_data, "owner2@example.com", OrganizationRole.OWNER
    )
    _cambiar_estado(
        client, segundo_owner, test_organization_data, test_user_data, "INACTIVE"
    )

    respuesta = _cambiar_estado(
        client,
        segundo_owner,
        test_organization_data,
        segundo_owner,
        "INACTIVE",
    )

    assert respuesta.status_code == status.HTTP_400_BAD_REQUEST


def test_404_si_no_hay_membresia_en_esa_organizacion(
    client, test_organization_data, test_user_data
):
    """Un id de usuario que nunca tuvo membresía en esta organización."""
    otro_id_de_usuario = uuid4()

    with patch(
        "app.api.deps.verify_cognito_token",
        return_value={"sub": test_user_data.cognito_sub},
    ):
        respuesta = client.patch(
            f"/api/v1/organizations/{test_organization_data.id}/users/{otro_id_de_usuario}/status",
            json={"status": "INACTIVE"},
            headers={"Authorization": "Bearer lo-que-sea"},
        )

    assert respuesta.status_code == status.HTTP_404_NOT_FOUND


# ── Auditoría ────────────────────────────────────────────────────────────


def test_el_cambio_queda_auditado(
    client, db_session, test_organization_data, test_user_data
):
    victima = _otro_usuario(db_session, test_organization_data, "auditado@example.com")

    _cambiar_estado(client, test_user_data, test_organization_data, victima, "INACTIVE")

    evento = (
        db_session.query(AccountEvent)
        .filter(
            AccountEvent.event_type == EventType.ORG_USER_STATUS_CHANGED.value,
            AccountEvent.target_id == victima.id,
        )
        .first()
    )
    assert evento is not None
    assert evento.event_metadata["old_status"] == "ACTIVE"
    assert evento.event_metadata["new_status"] == "INACTIVE"
    assert evento.actor_user_id == test_user_data.id
