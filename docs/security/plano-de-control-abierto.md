# El plano de control estuvo abierto a cualquier usuario autenticado

**Descubierto:** 22 de septiembre de 2026, al preparar las bajas de los huérfanos.
**Cerrado:** el mismo día, en `v1.36.0`.
**Severidad:** alta — escalada de privilegios horizontal y vertical sobre 20 rutas de escritura.

## Qué pasaba

`get_auth_cognito_or_paseto` intenta **Cognito primero**. Si el token es válido y el
usuario existe en `users`, devuelve autorización **sin comprobar ningún rol**:

```python
user = db.query(User).filter(User.cognito_sub == cognito_sub).first()
if not user:
    raise HTTPException(404)
# ...
return AuthResult(auth_type="cognito", ...)   # ← sin mirar service ni role
```

`required_service="gac"` y `required_role="GAC_ADMIN"` se aplicaban **únicamente** al
camino PASETO, que sólo se intenta si el de Cognito falla.

Consecuencia: **cualquiera que pudiera iniciar sesión en Nexus podía llamar a todo
`/internal/*`.**

## Alcance

20 rutas de escritura en el plano de control, entre ellas:

| Ruta | Qué permitía |
| --- | --- |
| `PATCH /internal/users/{id}/status` | Desactivar a cualquier usuario del sistema |
| `POST /internal/organizations` | Crear organizaciones |
| `PATCH /internal/organizations/{id}/status` | Suspender cualquier organización |
| `POST /internal/organizations/{id}/subscriptions/{id}/cancel` | Cancelar suscripciones ajenas |
| `DELETE /internal/plans/{id}` | Borrar planes |
| `POST`/`DELETE` `/internal/plans/{id}/capabilities/{code}` | Cambiar qué puede hacer cada plan |

Más las de lectura, que exponían el padrón entero de cuentas, organizaciones y usuarios
a cualquier cliente.

## Verificado por ejecución, no deducido

Un usuario normal —sin `is_master`, sin rol de GAC— con su token corriente de Cognito:

```
PATCH /api/v1/internal/users/{victima}/status  {"status": "INACTIVE"}
→ 200
→ la víctima quedó en INACTIVE
```

## Por qué no lo vio nadie

El patrón venía de `/internal/accounts` y se copió a cada módulo interno nuevo. Y el
test de autorización que debía cubrirlo **preguntaba lo que no era**:

```python
respuesta = authenticated_client.get("/api/v1/internal/users")   # sin cabecera
assert respuesta.status_code in (401, 403)
```

Eso comprueba «¿rechaza a quien no trae token?», que siempre fue cierto. La pregunta
era **«¿rechaza a quien trae otro token?»**, que era falsa. Un test en verde que no
podía ponerse rojo por la razón que importaba — el patrón que §18 persigue, cometido
dentro de un test de autorización.

## El arreglo

`get_auth_solo_servicio(required_service, required_role)`: **sólo acepta PASETO**, sin
camino de Cognito. Aplicado a los ocho módulos bajo `/internal/`.

**`trips` y `commands` NO se tocan, y es deliberado.** Declaran el mismo
`required_service="gac"`, pero son endpoints de usuario: `nexus-web` llama a
`/units/{id}/trips` con token de Cognito (`tripStore.js:46`) y los clientes móviles
también. Cerrar la factory entera habría roto la pantalla de viajes para todos. La
dualidad ahí es correcta; lo que estaba mal era que `/internal/*` la heredara.

## Que no vuelva a pasar

- Un endpoint interno es **servicio a servicio**. No hay persona detrás, así que no hay
  token de persona que valga. Si una interfaz necesita entrar, se le da un endpoint
  propio con autorización por rol, no se reabre esta puerta.
- **Un test de autorización que sólo prueba la ausencia de credencial no prueba nada.**
  Tiene que existir el caso «credencial válida de quien no debe pasar».

## Qué comprobar en el despliegue

Que GAC sigue funcionando: usa PASETO por `getInternalToken()` contra
`/internal/tokens/app` de `gac-api`, que emite `service: gac` / `role: GAC_ADMIN`. Su
camino no cambia. Si algo de GAC empieza a dar 403, es que alguna llamada iba con
credenciales de usuario y hay que darle su propia ruta.
