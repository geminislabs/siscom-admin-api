"""
Tests de órdenes.
"""

import pytest
from fastapi import status

pytestmark = pytest.mark.skip(
    reason="Orders API/schema drift pendiente de alinear con SQLite fixtures (PR-2)"
)


def test_create_order(authenticated_client, test_organization_data):
    """
    Test que crea una orden con order_items.
    """
    order_data = {
        "items": [
            {
                "item_type": "DEVICE",
                "description": "Dispositivo GPS Queclink GV300",
                "quantity": 2,
                "unit_price": "1500.00",
            },
            {
                "item_type": "ACCESSORY",
                "description": "Antena GPS externa",
                "quantity": 2,
                "unit_price": "200.00",
            },
        ]
    }

    response = authenticated_client.post("/api/v1/orders/", json=order_data)
    assert response.status_code == status.HTTP_201_CREATED

    data = response.json()
    assert data["status"] == "PENDING"
    assert float(data["total_amount"]) == 3400.00  # (1500*2) + (200*2)
    assert data["payment_id"] is not None
    assert len(data["order_items"]) == 2


def test_list_orders(authenticated_client, test_organization_data):
    """
    Test que lista órdenes de la organización.
    """
    # Crear una orden primero
    order_data = {
        "items": [
            {
                "item_type": "DEVICE",
                "description": "Dispositivo Test",
                "quantity": 1,
                "unit_price": "1000.00",
            },
        ]
    }
    authenticated_client.post("/api/v1/orders/", json=order_data)

    # Listar órdenes
    response = authenticated_client.get("/api/v1/orders/")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1


def test_get_order_detail(authenticated_client, test_organization_data):
    """
    Test que obtiene el detalle de una orden específica.
    """
    # Crear una orden
    order_data = {
        "items": [
            {
                "item_type": "SERVICE",
                "description": "Plan Mensual",
                "quantity": 1,
                "unit_price": "299.00",
            },
        ]
    }
    create_response = authenticated_client.post("/api/v1/orders/", json=order_data)
    order_id = create_response.json()["id"]

    # Obtener detalle
    response = authenticated_client.get(f"/api/v1/orders/{order_id}")
    assert response.status_code == status.HTTP_200_OK

    data = response.json()
    assert data["id"] == order_id
    assert float(data["total_amount"]) == 299.00
