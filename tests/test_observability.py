"""Tests unitarios de observabilidad. Sin Collector."""

import io
import json
import logging
from types import SimpleNamespace

from app.observability.init import (
    get_tracer_provider,
    reset_telemetry_for_tests,
    setup_telemetry,
    telemetry_enabled,
)
from app.observability.logging import (
    JSONFormatter,
    configure_json_logging,
    reset_logging_for_tests,
    scrub_value,
)


def _settings(**overrides):
    base = {
        "OTLP_ENDPOINT": "",
        "DEPLOY_ENV": "local",
        "SERVICE_NAME": "siscom-admin-api",
        "SERVICE_VERSION": "0.1.0",
        "LOG_LEVEL": "INFO",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_setup_telemetry_empty_endpoint_is_noop():
    reset_telemetry_for_tests()
    setup_telemetry(_settings(OTLP_ENDPOINT=""))
    assert telemetry_enabled() is False
    assert get_tracer_provider() is None


def test_setup_telemetry_empty_endpoint_does_not_raise():
    reset_telemetry_for_tests()
    setup_telemetry(_settings(OTLP_ENDPOINT="   "))
    assert telemetry_enabled() is False


def test_setup_telemetry_is_idempotent():
    reset_telemetry_for_tests()
    setup_telemetry(_settings(OTLP_ENDPOINT="http://localhost:4318"))
    first = get_tracer_provider()
    assert first is not None
    setup_telemetry(_settings(OTLP_ENDPOINT="http://localhost:4318"))
    assert get_tracer_provider() is first
    reset_telemetry_for_tests()


def test_configure_json_logging_emits_required_fields():
    reset_logging_for_tests()
    configure_json_logging(_settings(), level="INFO")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(
        JSONFormatter(service_name="siscom-admin-api", deploy_env="local")
    )
    logger = logging.getLogger("test.observability.json")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.info("auth.login.success", extra={"user_id": "u-1", "method": "cognito"})
    payload = json.loads(stream.getvalue())
    assert payload["message"] == "auth.login.success"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "test.observability.json"
    assert "timestamp" in payload
    assert payload["service.name"] == "siscom-admin-api"
    assert payload["deployment.environment"] == "local"
    assert "trace_id" in payload
    assert "span_id" in payload
    assert "request_id" in payload
    assert payload["user_id"] == "u-1"
    assert payload["method"] == "cognito"


def test_scrubber_redacts_password_in_extra():
    assert scrub_value("password", "hunter2") == "[REDACTED]"
    assert scrub_value("user_password", "x") == "[REDACTED]"
    nested = scrub_value("payload", {"refresh_token": "abc", "ok": 1})
    assert nested["refresh_token"] == "[REDACTED]"
    assert nested["ok"] == 1

    fmt = JSONFormatter()
    rec = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="x",
        lineno=1,
        msg="auth.login.failure",
        args=(),
        exc_info=None,
    )
    rec.password = "secret-value"
    data = json.loads(fmt.format(rec))
    assert data["password"] == "[REDACTED]"


# ---------------------------------------------------------------------------
# Corte 2 — el orden de los middlewares, la cardinalidad y el request_id
# ---------------------------------------------------------------------------


def _orden_de_middlewares():
    """Nombres de los middlewares HTTP, del mas externo al mas interno.

    Starlette construye la pila con `user_middleware[0]` por fuera, asi que el
    indice mas bajo es el mas externo.
    """
    import app.main as main_mod

    nombres = []
    for mw in main_mod.app.user_middleware:
        dispatch = getattr(mw, "kwargs", {}).get("dispatch")
        nombres.append(getattr(dispatch, "__name__", None) or mw.cls.__name__)
    return nombres


def test_request_id_envuelve_al_manejador_de_500():
    """Sin esto, los logs de los 500 salen sin `request_id`.

    El middleware de request_id resetea su ContextVar en un `finally`. Si queda
    por dentro del manejador de excepciones, cuando este loguea el 500 el valor
    ya se borro — y esa es justo la linea que uno busca para rastrear el fallo.
    """
    nombres = _orden_de_middlewares()

    assert "attach_request_id" in nombres
    assert "unhandled_exception_to_json" in nombres
    assert nombres.index("attach_request_id") < nombres.index(
        "unhandled_exception_to_json"
    )


def test_la_cabecera_del_request_id_es_legible_por_el_browser():
    """De poco sirve devolver el identificador si el cliente no puede leerlo."""
    import app.main as main_mod

    cors = [
        mw for mw in main_mod.app.user_middleware if mw.cls.__name__ == "CORSMiddleware"
    ]
    assert cors, "no hay CORSMiddleware registrado"
    assert "X-Request-ID" in cors[0].kwargs.get("expose_headers", [])


def test_la_metrica_de_error_usa_la_plantilla_y_no_el_path():
    """Un path crudo como etiqueta abre una serie por cada identificador."""
    from starlette.requests import Request

    import app.main as main_mod

    class _Ruta:
        path = "/api/v1/organizations/{organization_id}/users"

    con_ruta = Request(
        {"type": "http", "headers": [], "route": _Ruta(), "path": "/api/v1/x"}
    )
    assert (
        main_mod._plantilla_de_ruta(con_ruta)
        == "/api/v1/organizations/{organization_id}/users"
    )

    sin_ruta = Request(
        {"type": "http", "headers": [], "path": "/api/v1/organizations/9f8e/users"}
    )
    assert main_mod._plantilla_de_ruta(sin_ruta) == "unmatched"


def test_el_request_id_entrante_se_acepta_o_se_descarta_entero():
    from app.observability.request_id import MAX_REQUEST_ID, normalizar_request_id

    # Lo razonable pasa tal cual: permite encadenar el identificador del cliente.
    assert normalizar_request_id("abc-123_XYZ.7") == "abc-123_XYZ.7"

    # Lo demas se descarta y se genera uno nuevo, no se recorta: un valor a
    # medias se parece demasiado a uno bueno.
    for malo in (
        None,
        "",
        "   ",
        "abc\ndef",
        "a b",
        "x" * (MAX_REQUEST_ID + 1),
        "<script>",
    ):
        generado = normalizar_request_id(malo)
        assert generado != malo
        assert len(generado) == 36  # uuid4


def test_el_reset_de_tests_olvida_los_instrumentos_cacheados():
    """Un instrumento creado antes del setup se queda no-op para siempre."""
    from app.observability import metrics as metrics_mod
    from app.observability.init import reset_telemetry_for_tests

    metrics_mod.record_auth_attempt("cognito", "success")
    assert metrics_mod._counters, "el contador deberia haberse cacheado"

    reset_telemetry_for_tests()

    assert metrics_mod._counters == {}
