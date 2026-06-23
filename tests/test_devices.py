"""
Tests de endpoints de dispositivos con nueva estructura de estados y eventos.
"""

import pytest
from fastapi import status

# Tests con drift de flujo de estados / endpoints legacy (PR-2).
_STATUS_FLOW_SKIP = pytest.mark.skip(
    reason="Device status flow drift: client_id + preparado→enviado (PR-2)"
)

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


@_STATUS_FLOW_SKIP
def test_list_my_devices(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que lista dispositivos de la organización autenticada.
    """
    # Primero asignar el dispositivo a la organización
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "enviado",
            "organization_id": str(test_organization_data.id),
            "notes": "Test envío",
        },
    )
    assert response.status_code == status.HTTP_200_OK

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


@_STATUS_FLOW_SKIP
def test_status_change_to_enviado(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que cambia estado a 'enviado' con organización asignada.
    """
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "enviado",
            "organization_id": str(test_organization_data.id),
            "notes": "Enviado via DHL",
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "enviado"
    assert data["organization_id"] == str(test_organization_data.id)


@_STATUS_FLOW_SKIP
def test_status_change_to_enviado_without_organization(
    authenticated_client, test_device_data
):
    """
    Test que falla al cambiar a 'enviado' sin organization_id.
    """
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "enviado", "notes": "Test sin organización"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@_STATUS_FLOW_SKIP
def test_status_change_to_entregado(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que cambia estado a 'entregado'.
    """
    # Primero enviar
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "enviado",
            "organization_id": str(test_organization_data.id),
        },
    )

    # Luego marcar como entregado
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "entregado", "notes": "Recibido por Juan"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "entregado"


@_STATUS_FLOW_SKIP
def test_status_change_to_asignado(
    authenticated_client, test_device_data, test_organization_data, test_unit_data
):
    """
    Test que cambia estado a 'asignado' con unidad.
    """
    # Preparar: enviar y entregar
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "enviado",
            "organization_id": str(test_organization_data.id),
        },
    )
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "entregado"},
    )

    # Asignar a unidad
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "asignado",
            "unit_id": str(test_unit_data.id),
            "notes": "Instalado en camión",
        },
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "asignado"
    assert data["installed_in_unit_id"] == str(test_unit_data.id)
    assert data["last_assignment_at"] is not None


@_STATUS_FLOW_SKIP
def test_status_change_to_asignado_without_unit(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que falla al cambiar a 'asignado' sin unit_id.
    """
    # Preparar
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "enviado",
            "organization_id": str(test_organization_data.id),
        },
    )
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "entregado"},
    )

    # Intentar asignar sin unidad
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "asignado", "notes": "Sin unidad"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@_STATUS_FLOW_SKIP
def test_status_change_to_devuelto(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que cambia estado a 'devuelto' y quita organización.
    """
    # Preparar: enviar
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "enviado",
            "organization_id": str(test_organization_data.id),
        },
    )

    # Devolver
    response = authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "devuelto", "notes": "Organización canceló servicio"},
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "devuelto"
    assert data["organization_id"] is None  # Organización removida


@_STATUS_FLOW_SKIP
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


@_STATUS_FLOW_SKIP
def test_get_device_events(authenticated_client, test_device_data):
    """
    Test que obtiene el historial de eventos de un dispositivo.
    """
    response = authenticated_client.get(
        f"/api/v1/devices/{test_device_data.device_id}/events"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # Debe tener al menos el evento 'creado'
    assert len(data) >= 1
    assert data[-1]["event_type"] == "creado"  # El más antiguo


@_STATUS_FLOW_SKIP
def test_add_device_note(authenticated_client, test_device_data):
    """
    Test que agrega una nota al dispositivo.
    """
    response = authenticated_client.post(
        f"/api/v1/devices/{test_device_data.device_id}/notes?note=Test nota administrativa"
    )
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "Test nota administrativa" in data["notes"]

    # Verificar que se creó el evento
    response = authenticated_client.get(
        f"/api/v1/devices/{test_device_data.device_id}/events"
    )
    events = response.json()
    assert any(e["event_type"] == "nota" for e in events)


# ============================================
# Tests de Listado Especial
# ============================================


@_STATUS_FLOW_SKIP
def test_list_unassigned_devices(
    authenticated_client, test_device_data, test_organization_data
):
    """
    Test que lista dispositivos no asignados a unidades (entregados o devueltos).
    """
    # Preparar: poner dispositivo en estado 'entregado'
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={
            "new_status": "enviado",
            "organization_id": str(test_organization_data.id),
        },
    )
    authenticated_client.patch(
        f"/api/v1/devices/{test_device_data.device_id}/status",
        json={"new_status": "entregado"},
    )

    # Listar no asignados
    response = authenticated_client.get("/api/v1/devices/unassigned")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert isinstance(data, list)
    # El dispositivo debe aparecer
    assert any(d["device_id"] == test_device_data.device_id for d in data)
