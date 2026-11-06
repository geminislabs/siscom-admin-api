"""Ninguna ruta queda sin autenticación por descuido.

El 06/11/2026 se encontraron, en producción, `GET /devices`, `GET
/devices/{device_id}` y `GET /device-events/{device_id}` respondiendo sin
token: el inventario completo de todas las organizaciones —IMEI, `device_ref`,
ICCID, notas— para cualquiera. Ningún endpoint lo pedía a propósito; a las
tres simplemente les faltaba la dependencia.

Este test lee el OpenAPI, donde FastAPI declara `security` en toda operación
cuyo árbol de dependencias tiene un esquema de seguridad, y exige que las que
no lo tienen sean exactamente las de esta lista. Una ruta pública nueva tiene
que entrar aquí, con su porqué, en el mismo PR.
"""

from app.main import app

PUBLICAS = {
    ("GET", "/"): "raíz informativa",
    ("GET", "/health"): "sondeo del balanceador y del deploy",
    ("POST", "/api/v1/auth/login"): "es la que emite el token",
    ("POST", "/api/v1/auth/register"): "alta de cuenta",
    ("POST", "/api/v1/auth/verify-email"): "enlace de verificación por correo",
    ("POST", "/api/v1/auth/resend-verification"): "reenvío de verificación",
    ("POST", "/api/v1/auth/forgot-password"): "recuperación de contraseña",
    ("POST", "/api/v1/auth/reset-password"): "recuperación de contraseña",
    ("POST", "/api/v1/auth/refresh"): "valida el access token vencido por su cuenta",
    ("POST", "/api/v1/contact/send-message"): "formulario del sitio, con reCAPTCHA",
    ("GET", "/api/v1/invites/{token}"): "el token de la invitación es la credencial",
    (
        "POST",
        "/api/v1/users/accept-invitation",
    ): "el token de la invitación es la credencial",
    ("GET", "/api/v1/plans"): "catálogo de precios público",
    ("GET", "/api/v1/plans/{plan_identifier}"): "catálogo de precios público",
    ("GET", "/api/v1/tenant-config"): "marca del login, antes de autenticarse",
    ("GET", "/api/v1/devices/status"): "catálogo estático de estados",
}


def _sin_seguridad() -> set[tuple[str, str]]:
    esquema = app.openapi()
    return {
        (metodo.upper(), ruta)
        for ruta, operaciones in esquema["paths"].items()
        for metodo, operacion in operaciones.items()
        if not operacion.get("security")
    }


def test_las_rutas_sin_autenticacion_son_exactamente_las_publicas():
    sin_seguridad = _sin_seguridad()

    nuevas = sin_seguridad - set(PUBLICAS)
    assert not nuevas, f"Rutas sin autenticación que no están en PUBLICAS: {nuevas}"

    sobran = set(PUBLICAS) - sin_seguridad
    assert not sobran, f"Rutas en PUBLICAS que ya piden autenticación: {sobran}"
