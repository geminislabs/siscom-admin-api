from fastapi import APIRouter

from app.api.v1.endpoints.api_platform.routers import (
    alerts,
    keys,
    logs,
    throttles,
    usage,
)

api_platform_router = APIRouter()

api_platform_router.include_router(
    keys.router, prefix="/keys", tags=["api-platform-keys"]
)
api_platform_router.include_router(
    usage.router, prefix="/usage", tags=["api-platform-usage"]
)
api_platform_router.include_router(
    logs.router, prefix="/logs", tags=["api-platform-logs"]
)
api_platform_router.include_router(
    throttles.router, prefix="/throttles", tags=["api-platform-throttles"]
)
api_platform_router.include_router(
    alerts.router, prefix="/alerts", tags=["api-platform-alerts"]
)
