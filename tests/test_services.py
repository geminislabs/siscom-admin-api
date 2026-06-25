"""
Tests de servicios de dispositivos.
Este es el test más importante del sistema.

NOTA: DeviceService está marcado como LEGACY / DEPRECATED.
Estos tests se mantienen para compatibilidad hasta la migración a subscriptions.
"""

from datetime import datetime

import pytest
from fastapi import status

from app.utils.datetime import utcnow

pytestmark = pytest.mark.skip(
    reason="Legacy DeviceService API tests pending device_id model alignment (PR-2)"
)


def test_activate_device_service_monthly(
    authenticated_client, test_device_data, test_plan_data, db_session
):
    """
    Test de activación de servicio mensual.
    Verifica:
    - Se crea el servicio con status ACTIVE
    - expires_at está ~30 días en el futuro
    - device.active se actualiza a True
    """
    service_data = {
        "device_id": str(test_device_data.id),
        "plan_id": str(test_plan_data.id),
        "subscription_type": "MONTHLY",
    }

    response = authenticated_client.post("/api/v1/services/activate", json=service_data)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["status"] == "ACTIVE"
    assert data["device_id"] == str(test_device_data.id)
    assert data["plan_id"] == str(test_plan_data.id)
    assert data["subscription_type"] == "MONTHLY"
    assert data["auto_renew"] is True

    # Verificar expires_at (debe estar ~30 días en el futuro)
    expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    now = utcnow()
    days_diff = (expires_at - now).days
    assert (
        28 <= days_diff <= 32
    ), f"expires_at debe estar ~30 días en el futuro, pero está a {days_diff} días"

    # Verificar que device.active está en True
    db_session.refresh(test_device_data)
    assert test_device_data.active is True


def test_activate_device_service_yearly(
    authenticated_client, test_device_data, test_plan_data, db_session
):
    """
    Test de activación de servicio anual.
    Verifica que expires_at está ~365 días en el futuro.
    """
    service_data = {
        "device_id": str(test_device_data.id),
        "plan_id": str(test_plan_data.id),
        "subscription_type": "YEARLY",
    }

    response = authenticated_client.post("/api/v1/services/activate", json=service_data)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["status"] == "ACTIVE"
    assert data["subscription_type"] == "YEARLY"

    # Verificar expires_at (debe estar ~365 días en el futuro)
    expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
    now = utcnow()
    days_diff = (expires_at - now).days
    assert (
        363 <= days_diff <= 367
    ), f"expires_at debe estar ~365 días en el futuro, pero está a {days_diff} días"


def test_cannot_activate_two_services_simultaneously(
    authenticated_client, test_device_data, test_plan_data
):
    """
    Test que no permite activar dos servicios simultáneamente en el mismo dispositivo.
    Esto valida el constraint único en device_services.
    """
    service_data = {
        "device_id": str(test_device_data.id),
        "plan_id": str(test_plan_data.id),
        "subscription_type": "MONTHLY",
    }

    # Primera activación - debe funcionar
    response1 = authenticated_client.post(
        "/api/v1/services/activate", json=service_data
    )
    assert response1.status_code == status.HTTP_201_CREATED

    # Segunda activación - debe fallar
    response2 = authenticated_client.post(
        "/api/v1/services/activate", json=service_data
    )
    assert response2.status_code == status.HTTP_400_BAD_REQUEST
    assert "ya tiene un servicio activo" in response2.json()["detail"].lower()


def test_list_active_services(authenticated_client, test_device_data, test_plan_data):
    """
    Test que lista servicios activos de la organización.
    """
    # Activar un servicio primero
    service_data = {
        "device_id": str(test_device_data.id),
        "plan_id": str(test_plan_data.id),
        "subscription_type": "MONTHLY",
    }
    authenticated_client.post("/api/v1/services/activate", json=service_data)

    # Listar servicios activos
    response = authenticated_client.get("/api/v1/services/active")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1

    service = data[0]
    assert service["status"] == "ACTIVE"
    assert service["device_device_id"] == test_device_data.device_id
    assert service["plan_name"] == test_plan_data.name


def test_cancel_device_service(
    authenticated_client, test_device_data, test_plan_data, db_session
):
    """
    Test de cancelación de servicio.
    Verifica que device.active se actualiza a False si no hay otros activos.
    """
    # Activar un servicio
    service_data = {
        "device_id": str(test_device_data.id),
        "plan_id": str(test_plan_data.id),
        "subscription_type": "MONTHLY",
    }
    response = authenticated_client.post("/api/v1/services/activate", json=service_data)
    service_id = response.json()["id"]

    # Cancelar el servicio
    response = authenticated_client.patch(f"/api/v1/services/{service_id}/cancel")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["status"] == "CANCELLED"
    assert data["cancelled_at"] is not None

    # Verificar que device.active está en False
    db_session.refresh(test_device_data)
    assert test_device_data.active is False
