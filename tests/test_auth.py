"""
Tests de autenticación.
Verifica que los endpoints protegidos rechacen requests sin token válido.
"""

from fastapi import status


def test_endpoint_without_token_returns_401(client):
    """GET /organizations requiere autenticación."""
    response = client.get("/api/v1/organizations")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_endpoint_with_invalid_token_returns_401(client):
    """Token inválido en endpoint protegido."""
    headers = {"Authorization": "Bearer invalid_token_here"}
    response = client.get("/api/v1/organizations", headers=headers)
    assert response.status_code in [
        status.HTTP_401_UNAUTHORIZED,
        status.HTTP_400_BAD_REQUEST,
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        status.HTTP_503_SERVICE_UNAVAILABLE,
    ]


def test_devices_my_devices_endpoint_without_auth(client):
    """GET /devices/my-devices requiere autenticación."""
    response = client.get("/api/v1/devices/my-devices")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_services_endpoint_without_auth(client):
    """GET /services/active requiere autenticación."""
    response = client.get("/api/v1/services/active")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
