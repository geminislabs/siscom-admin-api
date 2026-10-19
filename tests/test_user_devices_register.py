from uuid import UUID, uuid4

from fastapi import status

from app.api.v1.endpoints import user_devices as user_devices_endpoint


def test_user_devices_register_returns_device_id(
    authenticated_client, monkeypatch, eventos_de_control
):
    monkeypatch.setattr(
        user_devices_endpoint,
        "get_or_recreate_endpoint",
        lambda device_token, platform, endpoint_arn=None: ("arn:aws:sns:test", False),
    )

    eventos_de_control.clear()

    payload = {
        "device_token": "test-token-123",
        "platform": "ios",
    }

    response = authenticated_client.post("/api/v1/user-devices/register", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data.get("id") is not None
    UUID(data["id"])
    assert data["device_token"] == payload["device_token"]

    # El evento lo emite el ORM al confirmar (control-plane-events).
    ((key, evento),) = eventos_de_control.de("user_device")
    assert evento["event_type"] == "UPSERT"
    assert evento["data"]["id"] == data["id"]
    assert evento["data"]["device_token"] == payload["device_token"]
    assert "unit_id" not in evento["data"]
    assert key == f"user_device:{data['id']}"


def test_user_devices_register_desactiva_al_dueno_anterior(
    authenticated_client,
    monkeypatch,
    db_session,
    test_organization_data,
    eventos_de_control,
):
    """En un aparato compartido, registrar el mismo device_token con otra
    cuenta desactiva la fila anterior -con su propio evento- en vez de
    reasignarla en silencio, que era el defecto que le apagaba el push a
    quien ya no es dueño de la sesión."""
    from app.models.user import User
    from app.models.user_device import UserDevice

    monkeypatch.setattr(
        user_devices_endpoint,
        "get_or_recreate_endpoint",
        lambda device_token, platform, endpoint_arn=None: ("arn:aws:sns:test", False),
    )

    previous_user = User(
        id=uuid4(),
        default_organization_id=test_organization_data.id,
        cognito_sub="previous-owner-sub",
        email="previous@test.com",
        full_name="Previous Owner",
    )
    db_session.add(previous_user)
    db_session.commit()

    shared_token = "shared-device-token"
    previous_row = UserDevice(
        user_id=previous_user.id,
        device_token=shared_token,
        platform="android",
        is_active=True,
    )
    db_session.add(previous_row)
    db_session.commit()
    db_session.refresh(previous_row)
    eventos_de_control.clear()

    payload = {"device_token": shared_token, "platform": "android"}
    response = authenticated_client.post("/api/v1/user-devices/register", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["id"] != str(previous_row.id)

    db_session.refresh(previous_row)
    assert previous_row.is_active is False
    assert previous_row.user_id == previous_user.id

    # Las dos filas salen en control-plane-events. La del dueño anterior sigue
    # existiendo, así que es UPSERT con is_active false, no DELETE.
    por_id = {e["data"]["id"]: e for _, e in eventos_de_control.de("user_device")}
    assert por_id[str(previous_row.id)]["event_type"] == "UPSERT"
    assert por_id[str(previous_row.id)]["data"]["is_active"] is False
    assert por_id[data["id"]]["data"]["is_active"] is True


def test_user_devices_register_mismo_usuario_reactiva_su_propia_fila(
    authenticated_client, monkeypatch, db_session, test_user_data
):
    """Si el propio usuario ya tenía una fila (inactiva) para ese token,
    la reactiva en vez de crear una duplicada."""
    from app.models.user_device import UserDevice

    monkeypatch.setattr(
        user_devices_endpoint,
        "get_or_recreate_endpoint",
        lambda device_token, platform, endpoint_arn=None: ("arn:aws:sns:test", False),
    )

    own_token = "own-old-token"
    own_row = UserDevice(
        user_id=test_user_data.id,
        device_token=own_token,
        platform="android",
        is_active=False,
    )
    db_session.add(own_row)
    db_session.commit()
    db_session.refresh(own_row)

    payload = {"device_token": own_token, "platform": "android"}
    response = authenticated_client.post("/api/v1/user-devices/register", json=payload)
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["id"] == str(own_row.id)
    assert data["is_active"] is True
