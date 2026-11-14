# Data token de GAC

`POST /api/v1/internal/data-token`

GAC muestra en su mapa de dispositivos las comunicaciones que guarda siscom-api
(el plano de datos). Las pide por un proxy de gac-web
(`src/lib/server/publicApiProxy.js`) y por un WebSocket. Mientras siscom-api
corre con `DATA_TOKEN_ENFORCED=false`, eso funciona sin credencial. Cuando la
bandera esté encendida, GAC necesita un data token, igual que la web y las apps,
y este endpoint es el que se lo da.

**Autenticación:** PASETO de servicio `gac` con rol `GAC_ADMIN`
(`get_auth_for_gac_admin`).

## Petición

```json
{ "device_ids": ["867564050638581"] }
```

- `device_ids`: IMEIs, entre 1 y 50. Se recortan espacios y se quitan repetidos.
  Si alguno está vacío, responde 422.

## Respuesta 200

```json
{
  "token": "v4.public.…",
  "expires_at": "2026-11-14T06:10:00Z",
  "expires_in": 600,
  "token_type": "Bearer",
  "devices": [
    { "device_id": "867564050638581", "device_ref": "0b9a…" }
  ]
}
```

A diferencia de `POST /auth/data-token`, aquí **sí** se devuelve el alcance.
GAC conoce los dispositivos por IMEI, pero siscom-api solo acepta `device_ref`,
así que el cliente necesita la traducción para poder usar el token.

## Cómo se usa contra siscom-api

- **HTTP:** `Authorization: Bearer <token>` y el `device_ref` en la ruta, por
  ejemplo `GET /api/v1/devices/{device_ref}/communications`.
- **WebSocket:** `GET /api/v1/stream?device_ids={device_ref}`, con el token en el
  subprotocolo: `Sec-WebSocket-Protocol: siscom.data-token.v1, <token>`.

## Qué concede

- **Solo los dispositivos pedidos**, sin unidades.
- **Toda la ventana de tiempo, histórico y en vivo:** es lo que el mapa de GAC ya
  muestra hoy.
- **La misma vida que el data token de una sesión de Nexus**
  (`DATA_TOKEN_MAX_TTL_SECONDS`, 10 minutos o menos). El cliente vuelve a pedirlo
  cuando caduca o cuando siscom-api responde 401 o 403.

En el índice de revocación, el dueño es el operador de GAC
(`ScopePurpose.GAC`, con un UUID derivado de su `internal_id`). Así, revocar
sesiones de Nexus nunca toca estos tokens, y al revés tampoco.

Cada emisión deja el log `internal.data_token.emitido`, con `gac_user`, `jti`
y el número de dispositivos. El `jti` se cruza con los logs de acceso de
siscom-api.

## Errores

| Código | Cuándo |
|--------|--------|
| 401 / 403 | Sin PASETO o con un rol distinto de `GAC_ADMIN` |
| 404 | Algún IMEI no existe. El cuerpo es `{"detail": "...", "missing": [...]}` y no se emite nada |
| 422 | Lista vacía, más de 50 IMEIs o un IMEI en blanco |
| 503 | Falta la clave de firma, Valkey o el secreto del índice de revocación |
