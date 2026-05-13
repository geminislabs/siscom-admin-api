from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware # type: ignore[attr-defined]

from app.api.deps import (
    close_geofences_kafka_producer,
    close_rules_kafka_producer,
    close_user_devices_kafka_producer,
)
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging_config import setup_logging
from app.services.health import check_kafka_accessibility
from app.startup import print_startup_banner

setup_logging()

@asynccontextmanager
async def lifespan(_: FastAPI):
    # Startup: verifica accesibilidad de servicios externos
    print_startup_banner()
    check_kafka_accessibility()

    yield

    # Shutdown: cierra recursos compartidos
    close_rules_kafka_producer()
    close_geofences_kafka_producer()
    close_user_devices_kafka_producer()

app = FastAPI(
    title=settings.PROJECT_NAME, version="1.0.0", docs_url="/docs", redoc_url="/redoc", lifespan=lifespan
)


# Middleware para limitar el tamaño del body y prevenir ataques DoS
@app.middleware("http")
async def limit_body_size(request: Request, call_next):
    """
    Middleware para limitar el tamaño del body de las peticiones.
    Previene ataques de denegación de servicio (DoS) con payloads grandes.

    Límite: 50KB (50,000 bytes)
    """
    max_body_size = 50000  # 50KB

    if request.headers.get("content-length"):
        content_length = int(request.headers["content-length"])
        if content_length > max_body_size:
            return Response(
                content="Payload demasiado grande. Máximo permitido: 50KB",
                status_code=413,
                media_type="text/plain",
            )

    return await call_next(request)

app.add_middleware(
    CORSMiddleware, # type: ignore[arg-type]
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
def health_check():
    """Health check endpoint para Docker y monitoring"""
    return {"status": "healthy", "service": "siscom-admin-api"}
