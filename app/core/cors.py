"""
CORS con una sola excepción: la declaración de marca.

`X-Brand-Host` es la declaración explícita de marca de las apps nativas (§26
del documento de arquitectura). Un navegador no tiene por qué mandarla —la web
resuelve su marca por `Host`, sin excepciones—, así que esta cabecera queda
fuera de CORS a propósito: el preflight que la pida se rechaza y el navegador
no envía la petición. El resto sigue como estaba, cualquier cabecera permitida.

Es una subclase y no una lista explícita en `allow_headers` porque esa lista
tendría que conocer cada cabecera que mandan hoy los clientes; olvidar una
rompe la web, y olvidarla aquí no cuesta nada.
"""

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import PlainTextResponse, Response

from app.services.tenancy import CABECERA_DE_MARCA


class CORSSinDeclaracionDeMarca(CORSMiddleware):
    def preflight_response(self, request_headers: Headers) -> Response:
        pedidas = request_headers.get("access-control-request-headers") or ""
        if CABECERA_DE_MARCA in {h.strip().lower() for h in pedidas.split(",")}:
            return PlainTextResponse("Disallowed CORS headers", status_code=400)
        return super().preflight_response(request_headers)
