"""ContextVar de request_id. No loguea body ni headers."""

from contextvars import ContextVar
from uuid import uuid4

from starlette.requests import Request
from starlette.responses import Response

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="")


def current_request_id() -> str:
    return request_id_ctx.get()


async def request_id_middleware(request: Request, call_next) -> Response:
    incoming = (request.headers.get("x-request-id") or "").strip() or str(uuid4())
    token = request_id_ctx.set(incoming)
    try:
        response = await call_next(request)
        response.headers["X-Request-ID"] = incoming
        return response
    finally:
        request_id_ctx.reset(token)
