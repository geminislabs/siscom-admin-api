"""Qué publica `control-plane-events` por cada escritura (ADR-008, contrato §3).

Los eventos no los emite cada endpoint: los emite el ORM al confirmar
(`app/services/messaging/control_plane.py`). Por eso casi todo se prueba
escribiendo con la sesión directamente: lo que se afirma es que **cualquier**
escritura emite, venga de donde venga. Un test va por HTTP para comprobar que
el camino de una petición real también confirma y publica.

El harness tiene las vistas `control_plane.*` de la 044 (`tests/conftest.py`),
así que los eventos se leen de las mismas vistas que en producción.
"""

from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.models.organization_user import OrganizationRole, OrganizationUser
from app.models.unit_device import UnitDevice
from app.models.user import User
from app.models.user_device import UserDevice
from app.models.user_unit import UserUnit
from app.services.messaging import control_plane


def _miembro(db, organizacion, email="miembro@example.com"):
    user = User(
        id=uuid4(),
        default_organization_id=organizacion.id,
        cognito_sub=f"sub-{uuid4()}",
        email=email,
        full_name="Miembro",
        is_master=False,
    )
    db.add(user)
    db.flush()
    db.add(
        OrganizationUser(
            organization_id=organizacion.id,
            user_id=user.id,
            role=OrganizationRole.MEMBER.value,
        )
    )
    db.commit()
    return user


def _membresia(db, organizacion, user):
    return (
        db.query(OrganizationUser)
        .filter(
            OrganizationUser.organization_id == organizacion.id,
            OrganizationUser.user_id == user.id,
        )
        .one()
    )


@pytest.fixture
def eventos(eventos_de_control):
    """El grabador, vacío: lo que publicaron los fixtures no cuenta."""
    eventos_de_control.clear()
    return eventos_de_control


# ---------------------------------------------------------------------------
# organization_user y user
# ---------------------------------------------------------------------------


def test_alta_de_miembro_publica_membresia_y_usuario(
    db_session, test_organization_data, eventos
):
    user = _miembro(db_session, test_organization_data)

    ((key, membresia),) = eventos.de("organization_user")
    assert key == f"organization_user:{test_organization_data.id}:{user.id}"
    assert membresia["event_type"] == "UPSERT"
    assert membresia["schema_version"] == 1
    assert membresia["organization_id"] == str(test_organization_data.id)
    assert membresia["data"] == {
        "organization_id": str(test_organization_data.id),
        "user_id": str(user.id),
        "role": "member",
        "status": "ACTIVE",
    }

    ((key, usuario),) = eventos.de("user")
    assert key == f"user:{user.id}"
    assert usuario["data"] == {"id": str(user.id), "status": "ACTIVE"}


def test_pausar_y_reactivar_son_upserts_con_otro_status(
    db_session, test_organization_data, eventos
):
    user = _miembro(db_session, test_organization_data)
    membresia = _membresia(db_session, test_organization_data, user)
    eventos.clear()

    membresia.status = "INACTIVE"
    db_session.commit()
    membresia.status = "ACTIVE"
    db_session.commit()

    estados = [e["data"]["status"] for _, e in eventos.de("organization_user")]
    tipos = {e["event_type"] for _, e in eventos.de("organization_user")}
    assert estados == ["INACTIVE", "ACTIVE"]
    assert tipos == {"UPSERT"}


def test_quitar_la_membresia_es_delete_con_la_clave(
    db_session, test_organization_data, eventos
):
    user = _miembro(db_session, test_organization_data)
    membresia = _membresia(db_session, test_organization_data, user)
    eventos.clear()

    db_session.delete(membresia)
    db_session.commit()

    ((key, evento),) = eventos.de("organization_user")
    assert key == f"organization_user:{test_organization_data.id}:{user.id}"
    assert evento["event_type"] == "DELETE"
    assert evento["data"] == {
        "organization_id": str(test_organization_data.id),
        "user_id": str(user.id),
    }


def test_baja_del_usuario_publica_user_y_otros_cambios_no(
    db_session, test_organization_data, eventos
):
    user = _miembro(db_session, test_organization_data)
    eventos.clear()

    user.full_name = "Otro nombre"
    db_session.commit()
    assert eventos.de("user") == []

    user.status = "INACTIVE"
    db_session.commit()
    ((_, evento),) = eventos.de("user")
    assert evento["data"] == {"id": str(user.id), "status": "INACTIVE"}


def test_un_rollback_no_publica_nada(db_session, test_organization_data, eventos):
    user = _miembro(db_session, test_organization_data)
    membresia = _membresia(db_session, test_organization_data, user)
    eventos.clear()

    membresia.status = "INACTIVE"
    db_session.flush()
    db_session.rollback()

    assert list(eventos) == []


# ---------------------------------------------------------------------------
# user_unit
# ---------------------------------------------------------------------------


def test_conceder_y_revocar_una_unidad(
    db_session, test_organization_data, test_unit_data, eventos
):
    user = _miembro(db_session, test_organization_data)
    eventos.clear()

    concesion = UserUnit(user_id=user.id, unit_id=test_unit_data.id, role="viewer")
    db_session.add(concesion)
    db_session.commit()
    db_session.delete(concesion)
    db_session.commit()

    (k1, alta), (k2, baja) = eventos.de("user_unit")
    assert k1 == k2 == f"user_unit:{user.id}:{test_unit_data.id}"
    assert alta["event_type"] == "UPSERT"
    assert alta["data"] == {
        "organization_id": str(test_organization_data.id),
        "user_id": str(user.id),
        "unit_id": str(test_unit_data.id),
        "role": "viewer",
    }
    assert baja["event_type"] == "DELETE"


def test_borrar_la_unidad_revoca_sus_concesiones(
    db_session, test_organization_data, test_unit_data, eventos
):
    """Nadie toca `user_units`, pero la vista deja de mostrarlas."""
    user = _miembro(db_session, test_organization_data)
    db_session.add(UserUnit(user_id=user.id, unit_id=test_unit_data.id))
    db_session.commit()
    eventos.clear()

    test_unit_data.deleted_at = datetime.now(timezone.utc)
    db_session.commit()

    ((key, evento),) = eventos.de("user_unit")
    assert key == f"user_unit:{user.id}:{test_unit_data.id}"
    assert evento["event_type"] == "DELETE"


# ---------------------------------------------------------------------------
# unit_device
# ---------------------------------------------------------------------------


def test_asignar_y_liberar_un_equipo(
    db_session, test_organization_data, test_unit_data, test_device_data, eventos
):
    asignacion = UnitDevice(
        unit_id=test_unit_data.id, device_id=test_device_data.device_id
    )
    db_session.add(asignacion)
    db_session.commit()

    asignacion.unassigned_at = datetime.now(timezone.utc)
    db_session.commit()

    (k1, alta), (k2, baja) = eventos.de("unit_device")
    assert k1 == k2 == f"unit_device:{test_device_data.device_id}"
    assert alta["event_type"] == "UPSERT"
    assert alta["data"] == {
        "device_id": test_device_data.device_id,
        "unit_id": str(test_unit_data.id),
        "organization_id": str(test_organization_data.id),
    }
    assert baja["event_type"] == "DELETE"
    assert baja["data"] == {"device_id": test_device_data.device_id}


# ---------------------------------------------------------------------------
# user_device
# ---------------------------------------------------------------------------


def test_desactivar_un_dispositivo_es_upsert_no_delete(
    db_session, test_user_data, eventos
):
    """En el topic viejo se publicaba DELETE; aquí la fila sigue existiendo."""
    dispositivo = UserDevice(
        user_id=test_user_data.id,
        device_token="token-1",
        platform="ios",
        endpoint_arn="arn:aws:sns:test",
        is_active=True,
    )
    db_session.add(dispositivo)
    db_session.commit()

    dispositivo.is_active = False
    db_session.commit()

    (_, alta), (key, baja) = eventos.de("user_device")
    assert key == f"user_device:{dispositivo.id}"
    assert alta["data"]["is_active"] is True
    assert baja["event_type"] == "UPSERT"
    assert baja["organization_id"] is None
    assert baja["data"]["is_active"] is False
    assert baja["data"]["device_token"] == "token-1"
    assert set(baja["data"]) == set(control_plane.ENTIDADES["user_device"].columnas)


def test_volver_a_registrar_sin_cambios_no_emite(db_session, test_user_data, eventos):
    """iOS llama a `register` varias veces por cada apertura de la app. Solo
    cambian `last_seen_at` y `updated_at`, y eso no es noticia para nadie: el
    19/10 una apertura producía cuatro eventos idénticos."""
    dispositivo = UserDevice(
        user_id=test_user_data.id,
        device_token="token-1",
        platform="ios",
        endpoint_arn="arn:aws:sns:test",
        is_active=True,
    )
    db_session.add(dispositivo)
    db_session.commit()
    eventos.clear()

    ahora = datetime.now(timezone.utc)
    dispositivo.last_seen_at = ahora
    dispositivo.updated_at = ahora
    db_session.commit()
    assert eventos.de("user_device") == []

    # Un token nuevo, en cambio, sí: es otro destino para el push.
    dispositivo.device_token = "token-2"
    dispositivo.updated_at = datetime.now(timezone.utc)
    db_session.commit()
    ((_, evento),) = eventos.de("user_device")
    assert evento["data"]["device_token"] == "token-2"


# ---------------------------------------------------------------------------
# Publicación
# ---------------------------------------------------------------------------


class _ProductorQueFalla:
    configurado = True

    def __init__(self):
        self.intentos = 0

    def publish_update(self, payload=None, key=None):
        self.intentos += 1
        return False

    def close(self):
        return None


def test_si_kafka_no_responde_reintenta_registra_y_no_tumba_el_commit(
    db_session, test_organization_data, caplog
):
    productor = _ProductorQueFalla()
    control_plane.usar_productor(lambda: productor)
    try:
        with patch.object(control_plane.time, "sleep"):
            user = _miembro(db_session, test_organization_data)
    finally:
        control_plane.usar_productor(None)

    # El commit ocurrió: la fila está.
    assert db_session.get(User, user.id) is not None
    # Dos eventos (user y organization_user), tres intentos cada uno.
    assert productor.intentos == 6
    fallos = [
        r for r in caplog.records if r.getMessage() == "control_event_publish_failed"
    ]
    assert {r.extra_data["entity"] for r in fallos} == {"user", "organization_user"}


def test_con_el_topic_vacio_no_se_publica(db_session, test_organization_data, eventos):
    with patch.object(control_plane.settings, "KAFKA_CONTROL_PLANE_TOPIC", ""):
        _miembro(db_session, test_organization_data)

    assert list(eventos) == []


# ---------------------------------------------------------------------------
# Por HTTP
# ---------------------------------------------------------------------------


def test_pausar_por_la_api_publica_la_membresia(
    client, db_session, test_organization_data, test_user_data, eventos
):
    """Mismo camino que `tests/test_membership_status_endpoint.py`."""
    user = _miembro(db_session, test_organization_data)
    eventos.clear()

    with patch(
        "app.api.deps.verify_cognito_token",
        return_value={"sub": test_user_data.cognito_sub},
    ):
        respuesta = client.patch(
            f"/api/v1/organizations/{test_organization_data.id}/users/{user.id}/status",
            json={"status": "INACTIVE"},
            headers={"Authorization": "Bearer lo-que-sea"},
        )

    assert respuesta.status_code == 200, respuesta.text
    estados = [e["data"]["status"] for _, e in eventos.de("organization_user")]
    assert estados[-1] == "INACTIVE"
