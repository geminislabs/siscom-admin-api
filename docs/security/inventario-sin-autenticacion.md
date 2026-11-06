# El inventario de dispositivos respondía sin autenticación

**Descubierto:** 6 de noviembre de 2026, auditando qué endpoints sirven histórico.
**Severidad:** alta — lectura sin credencial del inventario de todas las organizaciones.

## Qué pasaba

Tres rutas no tenían ninguna dependencia de autenticación:

| Ruta | Qué devolvía |
|---|---|
| `GET /api/v1/devices` | Inventario de todas las organizaciones: IMEI, `device_ref`, ICCID, cliente, notas |
| `GET /api/v1/devices/{device_id}` | Lo mismo, de un dispositivo |
| `GET /api/v1/device-events/{device_id}` | La bitácora del dispositivo: movimientos, unidades, quién los hizo |

Comprobado contra producción sin token: `GET /devices` → 200 con datos; `GET
/device-events/<IMEI inexistente>` → 404 «Dispositivo no encontrado» (y no 401).
La documentación decía «🔒 Todos requieren autenticación».

Que el `device_ref` saliera junto al IMEI anula el propósito de la referencia
opaca: existe para que el IMEI no llegue al navegador.

Además, `get_auth_for_gac_admin` —la dependencia de las rutas de escritura de
dispositivos y de todas las de SIMs— era `get_auth_cognito_or_paseto`, que deja
pasar a **cualquier** usuario de Cognito sin mirar el rol. Es el mismo agujero
que tuvo `/internal/*` (`plano-de-control-abierto.md`).

## Qué se cambió

- `GET /devices` y `GET /devices/{device_id}` piden `get_auth_for_gac_admin`.
- `get_auth_for_gac_admin` pasa a `get_auth_solo_servicio`: sólo PASETO de GAC.
  Nadie llamaba a estas rutas con Cognito: GAC (`gac-web`, `internalApi`) y el
  worker de demo mandan PASETO.
- `GET /device-events/{device_id}` se retira: ningún cliente lo llamaba (cero
  referencias en los repos).
- `tests/test_rutas_publicas.py` exige que las rutas sin autenticación sean
  exactamente una lista explícita, con su porqué. Una ruta nueva sin
  dependencia rompe la CI.

## Pendiente

No hay registro de acceso de esas rutas anterior al cambio que permita saber
si alguien las usó. Si los logs del balanceador lo conservan, buscar peticiones
a `/api/v1/devices` y `/api/v1/device-events/` sin cabecera `Authorization`.
