"""
Tests de endpoints de dispositivos con nueva estructura de estados y eventos.
"""

from fastapi import status


def _set_status(client, device_id, new_status, **extra):
    """Aplica una transición de estado vía PATCH /devices/{id}/status."""
    body = {"new_status": new_status, **extra}
    return client.patch(f"/api/v1/devices/{device_id}/status", json=body)


def _advance_to_entregado(client, device_id, organization_id):
    """Recorre el flujo nuevo→preparado→enviado→entregado y valida cada paso.

    La organización se asigna al preparar (client_id); el envío exige estado
    'preparado' previo. Devuelve la respuesta de la transición a 'entregado'.
    """
    prepared = _set_status(
        client, device_id, "preparado", client_id=str(organization_id)
    )
    assert prepared.status_code == status.HTTP_200_OK

    shipped = _set_status(client, device_id, "enviado")
    assert shipped.status_code == status.HTTP_200_OK

    delivered = _set_status(client, device_id, "entregado")
    assert delivered.status_code == status.HTTP_200_OK
    return delivered


# ============================================
# Tests de Creación y Listado
# ============================================


def test_create_device(authenticated_client, test_organization_data):
    """
    Test que crea un nuevo dispositivo en estado 'nuevo' sin organización asignada.
    """
    device_data = {
        "device_id": "999888777666555",
        "brand": "TestBrand",
        "model": "TestModel",
        "firmware_version": "1.0.0",
        "notes": "Dispositivo de prueba",
    }
    response = authenticated_client.post("/api/v1/devices", json=device_data)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["device_id"] == device_data["device_id"]
    assert data["brand"] == device_data["brand"]
    assert data["model"] == device_data["model"]
    assert data["status"] == "nuevo"
    assert data["client_id"] is None  # Sin organización asignada
    assert data["firmware_version"] == "1.0.0"
    assert data["iccid"] is None  # Sin ICCID


def test_create_device_with_iccid(authenticated_client, test_organization_data):
    """
    Test que crea un nuevo dispositivo con ICCID de SIM.
    """
    device_data = {
        "device_id": "888777666555444",
        "brand": "TestBrand",
        "model": "TestModel",
        "firmware_version": "1.0.0",
        "notes": "Dispositivo con SIM",
        "iccid": "89340123456789012345",
    }
    response = authenticated_client.post("/api/v1/devices", json=device_data)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["device_id"] == device_data["device_id"]
    assert data["iccid"] == device_data["iccid"]


def test_create_device_duplicate_device_id(authenticated_client, test_device_data):
    """
    Test que no permite crear dispositivo con device_id duplicado.
    """
    device_data = {
        "device_id": test_device_data.device_id,  # device_id ya existe
        "brand": "TestBrand",
        "model": "TestModel",
    }
    response = authenticated_client.post("/api/v1/devices", json=device_data)
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_list_devices(authenticated_client, test_device_data):
    """
    Test que lista todos los dispositivos con filtros.
    """
    response = authenticated_client.get("/api/v1/devices")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_list_devices_by_status(authenticated_client, test_device_data):
    """
    Test que filtra dispositivos por estado.
    """
    response = authenticated_client.get("/api/v1/devices?status_filter=nuevo")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Todos los dispositivos deben tener status='nuevo'
    for device in data:
        assert device["status"] == "nuevo"


def test_list_my_devices(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que lista dispositivos de la organización autenticada.
    """
    # Asignar el dispositivo a la organización vía el flujo preparado→enviado
    prepared = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "preparado",
        client_id=str(test_organization_data.id),
        notes="Test envío",
    )
    assert prepared.status_code == status.HTTP_200_OK

    shipped = _set_status(authenticated_client, test_device_data.device_id, "enviado")
    assert shipped.status_code == status.HTTP_200_OK

    # Ahora listar mis dispositivos
    response = authenticated_client.get("/api/v1/devices/my-devices")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    assert any(d["device_id"] == test_device_data.device_id for d in data)


def test_get_device_detail(authenticated_client, test_device_data):
    """
    Test que obtiene el detalle de un dispositivo por device_id.
    """
    response = authenticated_client.get(f"/api/v1/devices/{test_device_data.device_id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["device_id"] == test_device_data.device_id


def test_get_device_not_found(authenticated_client):
    """
    Test que retorna 404 para dispositivo inexistente.
    """
    response = authenticated_client.get("/api/v1/devices/NOEXISTE123")
    assert response.status_code == status.HTTP_404_NOT_FOUND


# ============================================
# Tests de Actualización
# ============================================


def test_update_device_info(authenticated_client, test_device_data):
    """
    Test que actualiza información básica del dispositivo.
    """
    update_data = {
        "brand": "UpdatedBrand",
        "model": "UpdatedModel",
        "firmware_version": "2.0.0",
        "notes": "Actualizado",
    }
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}", json=update_data
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["brand"] == "UpdatedBrand"
    assert data["model"] == "UpdatedModel"
    assert data["firmware_version"] == "2.0.0"


def test_update_device_add_iccid(authenticated_client, test_device_data):
    """
    Test que agrega un ICCID a un dispositivo existente.
    """
    update_data = {
        "iccid": "89340123456789012345",
    }
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}", json=update_data
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["iccid"] == update_data["iccid"]


def test_update_device_change_iccid(authenticated_client, test_device_data):
    """
    Test que actualiza el ICCID de un dispositivo.
    """
    # Primero agregar un ICCID
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}",
        json={"iccid": "89340123456789012345"},
    )

    # Luego actualizar a otro ICCID
    new_iccid = "89340987654321098765"
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}", json={"iccid": new_iccid}
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["iccid"] == new_iccid


def test_get_device_with_iccid(authenticated_client, test_device_data):
    """
    Test que obtiene un dispositivo con su ICCID.
    """
    # Primero agregar un ICCID
    iccid = "89340123456789012345"
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}", json={"iccid": iccid}
    )

    # Obtener el dispositivo
    response = authenticated_client.get(f"/api/v1/devices/{test_device_data.device_id}")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["iccid"] == iccid


def test_list_devices_includes_iccid(authenticated_client, test_device_data):
    """
    Test que la lista de dispositivos incluye el campo ICCID.
    """
    # Agregar ICCID a un dispositivo
    iccid = "89340123456789012345"
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}", json={"iccid": iccid}
    )

    # Listar dispositivos
    response = authenticated_client.get("/api/v1/devices")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()

    # Buscar el dispositivo de prueba
    device = next(d for d in data if d["device_id"] == test_device_data.device_id)
    assert device["iccid"] == iccid


# ============================================
# Tests de Cambios de Estado
# ============================================


def test_status_change_to_enviado(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que cambia estado a 'enviado' tras preparar con organización asignada.
    """
    prepared = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "preparado",
        client_id=str(test_organization_data.id),
    )
    assert prepared.status_code == status.HTTP_200_OK

    response = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "enviado",
        notes="Enviado via DHL",
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "enviado"
    assert data["client_id"] == str(test_organization_data.id)


def test_status_change_requires_organization_to_prepare(
    authenticated_client, test_device_data
):
    """
    Test que falla al 'preparar' sin client_id.

    La organización se asigna al preparar; sin ella no puede avanzar el flujo
    de envío. Esta es la validación que antes se esperaba en 'enviado'.
    """
    response = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "preparado",
        notes="Test sin organización",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_status_change_to_entregado(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que cambia estado a 'entregado' tras el flujo preparado→enviado.
    """
    delivered = _advance_to_entregado(
        authenticated_client,
        test_device_data.device_id,
        test_organization_data.id,
    )
    data = delivered.json()
    assert data["status"] == "entregado"


def test_status_change_to_asignado(
    authenticated_client, test_device_data, test_organization_data, test_unit_data
):
    """
    Test que cambia estado a 'asignado' con unidad.
    """
    _advance_to_entregado(
        authenticated_client,
        test_device_data.device_id,
        test_organization_data.id,
    )

    response = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "asignado",
        unit_id=str(test_unit_data.id),
        notes="Instalado en camión",
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "asignado"
    assert data["last_assignment_at"] is not None


def test_status_change_to_asignado_without_unit(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que falla al cambiar a 'asignado' sin unit_id.
    """
    _advance_to_entregado(
        authenticated_client,
        test_device_data.device_id,
        test_organization_data.id,
    )

    response = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "asignado",
        notes="Sin unidad",
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


def test_status_change_to_devuelto(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que cambia estado a 'devuelto' y quita la organización.
    """
    prepared = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "preparado",
        client_id=str(test_organization_data.id),
    )
    assert prepared.status_code == status.HTTP_200_OK

    shipped = _set_status(authenticated_client, test_device_data.device_id, "enviado")
    assert shipped.status_code == status.HTTP_200_OK

    response = _set_status(
        authenticated_client,
        test_device_data.device_id,
        "devuelto",
        notes="Organización canceló servicio",
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "devuelto"
    assert data["client_id"] is None  # Organización removida


def test_status_change_to_inactivo(authenticated_client, test_device_data):
    """
    Test que cambia estado a 'inactivo' (baja definitiva).
    """
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "inactivo", "notes": "Dispositivo dañado"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "inactivo"


# ============================================
# Tests de Eventos
# ============================================


def test_get_device_events(authenticated_client):
    """
    Test que obtiene el historial de eventos de un dispositivo.
    """
    # Crear el dispositivo vía API para que se registre el evento 'creado'
    device_data = {
        "device_id": "111222333444555",
        "brand": "TestBrand",
        "model": "TestModel",
    }
    created = authenticated_client.post("/api/v1/devices", json=device_data)
    assert created.status_code == status.HTTP_201_CREATED

    response = authenticated_client.get(
        f"/api/v1/device-events/{device_data['device_id']}"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Debe tener al menos el evento 'creado'
    assert len(data) >= 1
    # Eventos ordenados del más reciente al más antiguo: el más antiguo es 'creado'
    assert data[-1]["event_type"] == "creado"


def test_add_device_note(authenticated_client, test_device_data):
    """
    Test que agrega una nota al dispositivo y registra el evento 'nota'.
    """
    response = authenticated_client.post(
        f"/api/v1/devices/{test_device_data.device_id}/notes?note=Test nota administrativa"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "Test nota administrativa" in data["notes"]

    # Verificar que se creó el evento en la bitácora
    response = authenticated_client.get(
        f"/api/v1/device-events/{test_device_data.device_id}"
    )
    assert response.status_code == status.HTTP_200_OK
    events = response.json()
    assert any(e["event_type"] == "nota" for e in events)


# ============================================
# Tests de Listado Especial
# ============================================


def test_list_unassigned_devices(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que lista dispositivos no asignados a unidades (entregados o devueltos).
    """
    # Llevar el dispositivo a 'entregado' (sin asignación a unidad)
    _advance_to_entregado(
        authenticated_client,
        test_device_data.device_id,
        test_organization_data.id,
    )

    # Listar no asignados
    response = authenticated_client.get("/api/v1/devices/unassigned")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # El dispositivo debe aparecer
    assert any(d["device_id"] == test_device_data.device_id for d in data)
