"""Autorización de `POST /user-devices/deactivate`.

Este endpoint no tenía ni un test, y no es un detalle: es la razón de que
viviera sin autenticación sin que nadie lo notara. Medido contra producción el
26/09/2026 devolvía **404** sin cabecera —la búsqueda se ejecutaba— mientras
`GET /users/me` devolvía 401.

El test que importa es el segundo. Un test de autorización que sólo prueba la
*ausencia* de credencial no prueba nada: la pregunta es si rechaza a quien trae
**otra** credencial válida.
"""

from uuid import uuid4

from fastapi import status

from app.models.user import User
from app.models.user_device import UserDevice


def _crear_dispositivo(db_session, *, user_id, token="token-de-prueba"):
    device = UserDevice(
        user_id=user_id,
        device_token=token,
        platform="android",
        endpoint_arn="arn:aws:sns:test",
        is_active=True,
    )
    db_session.add(device)
    db_session.commit()
    db_session.refresh(device)
    return device


def test_deactivate_sin_credencial_es_401(client, db_session, test_user_data):
    """Sin cabecera no se llega a mirar la base."""
    device = _crear_dispositivo(db_session, user_id=test_user_data.id)

    response = client.post(
        "/api/v1/user-devices/deactivate",
        json={"device_token": device.device_token},
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    db_session.refresh(device)
    assert device.is_active is True


def test_deactivate_con_credencial_de_quien_no_es_dueno_no_toca_la_fila(
    authenticated_client, db_session, test_organization_data, test_user_data
):
    """Una sesión válida no alcanza: hace falta ser el dueño del aparato.

    Se responde 404 y no 403 a propósito — un 403 confirmaría que ese device
    token existe, que es el oráculo que este arreglo viene a cerrar.
    """
    otro = User(
        id=uuid4(),
        organization_id=test_organization_data.id,
        cognito_sub="cognito-sub-de-otro",
        email="otro@example.com",
        full_name="Otro Usuario",
    )
    db_session.add(otro)
    db_session.commit()

    device = _crear_dispositivo(
        db_session, user_id=otro.id, token="token-de-otra-persona"
    )
    assert device.user_id != test_user_data.id

    response = authenticated_client.post(
        "/api/v1/user-devices/deactivate",
        json={"device_token": device.device_token},
    )

    assert response.status_code == status.HTTP_404_NOT_FOUND

    db_session.refresh(device)
    assert device.is_active is True


def test_deactivate_del_dueno_apaga_el_aparato(
    authenticated_client, db_session, test_user_data
):
    device = _crear_dispositivo(
        db_session, user_id=test_user_data.id, token="token-propio"
    )

    response = authenticated_client.post(
        "/api/v1/user-devices/deactivate",
        json={"device_token": device.device_token},
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["is_active"] is False

    db_session.refresh(device)
    assert device.is_active is False
