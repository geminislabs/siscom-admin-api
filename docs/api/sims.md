# API de SIMs

## Descripcion

Endpoints para operaciones de sincronizacion de SIMs con KORE Wireless.

Actualmente este modulo expone la sincronizacion masiva de SIMs remotas hacia las tablas locales `sim_cards` y `sim_kore_profiles`.

---

## Endpoint Disponible

### Sincronizar SIMs desde KORE

**POST** `/api/v1/sims/sync/kore`

Consulta KORE (`{KORE_API}Sims`) de forma paginada, y aplica upsert local:

- Actualiza `sim_cards` por `iccid`.
- Crea `sim_cards` faltantes aunque no exista `devices.device_id` compatible.
- Crea/actualiza `sim_kore_profiles` usando `sid` de KORE como `kore_sim_id`.

### Autenticacion

```text
Authorization: Bearer <access_token>
```

Acepta:

- JWT de Cognito (usuario autenticado)
- Token PASETO de servicio `gac` con rol `GAC_ADMIN`

### Request Body

No requiere body.

### Response 200

```json
{
  "total_remote_sims": 125,
  "matched_existing_sim_cards": 80,
  "sim_cards_created": 20,
  "sim_cards_updated": 35,
  "sim_cards_skipped_missing_device": 24,
  "kore_profiles_created": 22,
  "kore_profiles_updated": 58,
  "invalid_remote_records": 1
}
```

### Campos de Respuesta

| Campo | Tipo | Descripcion |
| ----- | ---- | ----------- |
| `total_remote_sims` | int | Total de SIMs recibidas desde KORE |
| `matched_existing_sim_cards` | int | SIMs remotas que ya tenian `sim_card` local por ICCID |
| `sim_cards_created` | int | Registros nuevos creados en `sim_cards` |
| `sim_cards_updated` | int | Registros existentes actualizados en `sim_cards` |
| `sim_cards_skipped_missing_device` | int | Campo de compatibilidad (actualmente esperado en `0`) |
| `kore_profiles_created` | int | Registros nuevos creados en `sim_kore_profiles` |
| `kore_profiles_updated` | int | Registros existentes actualizados en `sim_kore_profiles` |
| `invalid_remote_records` | int | Registros remotos ignorados por falta de `sid` o `iccid` |

### Errores

| Codigo | Causa |
| ------ | ----- |
| `503 Service Unavailable` | Error de autenticacion con KORE o configuracion incompleta |
| `502 Bad Gateway` | Error consultando la API de KORE |
| `401 Unauthorized` | Token de autenticacion invalido |

---

## Reglas de Negocio Importantes

1. `sid` de KORE se guarda como `kore_sim_id` en `sim_kore_profiles`.
2. Si no existe un device local para un `iccid`, la `sim_card` se crea con `device_id = NULL`.
3. El endpoint es idempotente: puede ejecutarse varias veces y solo aplica cambios necesarios.

---

## Ejemplo curl

```bash
curl -X POST "http://localhost:8000/api/v1/sims/sync/kore" \
  -H "Authorization: Bearer <token>"
```
