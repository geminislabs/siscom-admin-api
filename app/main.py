import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware  # type: ignore[attr-defined]
from fastapi.responses import JSONResponse

from app.api.deps import (
    close_geofences_kafka_producer,
    close_mobility_kafka_producer,
    close_rules_kafka_producer,
    close_unit_devices_kafka_producer,
    close_user_devices_kafka_producer,
    close_user_units_kafka_producer,
)
from app.api.v1.router import api_router
from app.core.config import settings
from app.observability.init import instrument_app, setup_telemetry
from app.observability.logging import configure_json_logging
from app.observability.metrics import record_api_error
from app.observability.request_id import request_id_middleware
from app.services.health import (
    check_database,
    check_kafka_accessibility,
    get_schema_revision,
)
from app.startup import print_startup_banner

configure_json_logging(settings)
setup_telemetry(settings)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: verifica accesibilidad de servicios externos
    print_startup_banner()
    check_kafka_accessibility()
    from app.services.gateways import initialize_gateways

    initialize_gateways()

    yield

    # Shutdown: cierra recursos compartidos
    close_rules_kafka_producer()
    close_geofences_kafka_producer()
    close_user_devices_kafka_producer()
    close_unit_devices_kafka_producer()
    close_user_units_kafka_producer()
    close_mobility_kafka_producer()


app = FastAPI(
    title=settings.PROJECT_NAME,
    # Version del contrato de la API (OpenAPI), no la del build: son cosas
    # distintas y mezclarlas hacia que SERVICE_VERSION tocara el esquema.
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

instrument_app(app)


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    return await request_id_middleware(request, call_next)


# Middleware para limitar el tamaño del body y prevenir ataques DoS
@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """
    Middleware para limitar el tamaño del body de las peticiones.
    Previene ataques de denegación de servicio (DoS) con payloads grandes.

    Límite: 50KB (50,000 bytes)
    """
    max_body_size = 50_000  # 50KB

    if "/stripe/webhook/" in request.url.path:
        return await call_next(request)

    if request.headers.get("content-length"):
        content_length = int(request.headers["content-length"])
        if content_length > max_body_size:
            return Response(
                content="Payload demasiado grande. Máximo permitido: 50KB",
                status_code=413,
                media_type="text/plain",
            )

    return await call_next(request)


@app.middleware("http")
async def unhandled_exception_to_json(request: Request, call_next):
    """
    Captura excepciones no manejadas por dentro de CORSMiddleware.
    Starlette pone ServerErrorMiddleware por fuera de CORS; un 500 crudo
    llega al browser sin Access-Control-Allow-Origin y se reporta como CORS.
    """
    try:
        return await call_next(request)
    except Exception as exc:
        record_api_error(request.url.path, type(exc).__name__)
        logger.exception(
            "http.unhandled_exception",
            extra={"http_method": request.method, "http_path": request.url.path},
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )


app.add_middleware(
    CORSMiddleware,  # type: ignore[arg-type]
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_V1_STR)


@app.get("/")
def root():
    return {"status": "ok", "message": "SISCOM Admin API running"}


@app.get("/health")
def health_check(response: Response):
    """Health check para Docker, el ALB y el bucle de espera del despliegue.

    Consulta la base. Si no responde, devuelve 503 y el contenedor pasa a
    unhealthy: es la senal que el despliegue necesita para abortar en vez de
    declarar exito sobre una base inservible.
    """
    # El detalle del fallo no sale de aqui: check_database() ya lo dejo en el
    # log. Ver el comentario de mas abajo.
    db_ok, _ = check_database()

    payload = {
        "status": "healthy" if db_ok else "unhealthy",
        "service": settings.SERVICE_NAME,
        "environment": settings.DEPLOY_ENV,
        "version": settings.SERVICE_VERSION,
        "database": "ok" if db_ok else "unreachable",
        # None significa que alembic nunca gestiono este esquema.
        "schema_revision": get_schema_revision() if db_ok else None,
    }
    if not db_ok:
        response.status_code = 503
        # Mensaje generico a proposito. /health no exige autenticacion, y el
        # str() de una excepcion de SQLAlchemy trae el host, el puerto y el
        # usuario de la conexion --a veces la sentencia entera--. Devolverlo
        # convertia una base caida en un mapa de la infraestructura para quien
        # sondee el endpoint. El error real queda en el log de check_database(),
        # que es donde hace falta para diagnosticar. (CodeQL py/stack-trace-exposure)
        payload["detail"] = "database unreachable"

    return payload
