from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.deps import (
    close_geofences_kafka_producer,
    close_rules_kafka_producer,
    close_user_devices_kafka_producer,
)
from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging_config import setup_logging
from app.services.health import check_kafka_accessibility

setup_logging()

app = FastAPI(
    title=settings.PROJECT_NAME, version="1.0.0", docs_url="/docs", redoc_url="/redoc"
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


# CORS Configuration
origins = [
    "http://localhost",
    "http://localhost:3000",  # Common frontend port
    "http://localhost:8080",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://10.8.0.1:5160",
    "http://localhost:5160",
    "http://127.0.0.1:5160",
    "http://10.8.0.1:8100",
    "http://10.8.0.1:5160",
    "http://127.0.0.1:8100",
    "*",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
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


@app.on_event("startup")
def on_startup() -> None:
    """Verifica accesibilidad de servicios externos al iniciar la aplicación."""
    setup_logging()
    check_kafka_accessibility()


@app.on_event("shutdown")
def on_shutdown() -> None:
    """Cierra recursos compartidos al apagar la aplicación."""
    close_rules_kafka_producer()
    close_geofences_kafka_producer()
    close_user_devices_kafka_producer()
