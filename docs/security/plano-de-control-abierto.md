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

---

# Segunda parte: el arreglo era esquivable

**Descubierto:** el mismo 22 de septiembre, **horas después de desplegar el arreglo de arriba**, al
preparar el token para ejecutar las bajas de los huérfanos.

## Qué pasaba

Cerrar `/internal/*` a «sólo PASETO» no sirve de nada **si cualquiera puede fabricarse un PASETO**.

`POST /api/v1/auth/internal` firmaba un token de servicio con el `service` y el `role` que pidiera
quien llamara, hasta **720 horas** de validez, y como única autorización `get_current_user` — que
sólo valida el token de Cognito, sin mirar ningún rol.

Verificado por ejecución:

```
POST /api/v1/auth/internal   {"service":"gac","role":"GAC_ADMIN","expires_in_hours":720}
Authorization: Bearer <token de un usuario normal>
→ 200
→ v4.local.oXXEb89fXr31gr_i9QpBqkjH8N9-b1G…   caduca en 30 días
```

Peor que el original en un aspecto: ese token **dura un mes y parece legítimo**. Un PASETO de
servicio en los logs no levanta sospechas; el que emite GAC dura cinco minutos.

## Cómo se encontró, que es lo que más dice

Por accidente. El dueño del sistema perdió su token y hubo que buscar cómo emitir otro. Si lo
hubiera tenido a mano, las bajas habrían salido bien y el agujero seguiría abierto — con el
arreglo de la `v1.36.0` desplegado y dando sensación de haber cerrado algo.

**El error de método fue cerrar la puerta que estaba mirando sin preguntar quién puede fabricar la
llave.** Perímetro incompleto: se verificó una pieza y se trató como si fuera el sistema.

## El arreglo

**Se borra el endpoint.** Medido antes de decidir:

| Pregunta | Respuesta |
| --- | --- |
| ¿Cuántas rutas firman un token de servicio? | Una |
| ¿Quién la llama? | **Nadie** — cero referencias en los nueve repositorios |
| ¿Cómo consigue GAC su PASETO? | Lo firma él mismo (`create_app_token`), detrás de `require_roles(["admin"])` |
| ¿Qué decía la documentación? | Que `gac-web` la usaba — **texto viejo**, el código va por `gac-api` desde hace tiempo |

Sin endpoint no hay techo de 720 horas que bajar ni comprobación de rol que escribir mal. Para
emitir un token de operación a mano: entrar en GAC como administrador.

## El entorno de demo

Corre `siscom-admin-api` anclado tres meses atrás (155 commits), con **los dos agujeros abiertos**,
y Caddy expone `/api/v1/*` entero.

**Está contenido**, y se comprobó antes de decidir: usa `cognito-local` con su propio pool, y
`gen-secrets.sh` genera su `PASETO_SECRET_KEY` con `openssl rand`. **Un token acuñado allí no vale
contra producción.** El radio es la demo y sus datos.

Se cierra en el repositorio de la demo bloqueando las dos rutas en Caddy — el *gate* y el *worker*
hablan directo con `siscom-admin-api:8100` y no las usan — sin tocar el código ni mover el
submódulo.

## Lo que queda anotado

- **Auditar la política de `EC2-SISCOM-SES-Role`.** Un rol de SES con responsabilidades de Cognito
  añadidas por acumulación. El 22/09 le faltaban `AdminDisableUser` y `AdminEnableUser`.
- **El *overlay* del entorno de demo** mantiene su propia copia de `auth.py`, de junio. Ahora
  además contiene un endpoint que en el repositorio principal ya no existe.
- **La documentación describía protecciones que ningún código sostenía** («no debe exponerse
  públicamente», «protegerlo con firewall o VPN»). Una nota que describe la intención correcta y
  que nada verifica es peor que no tenerla: quien la lee cree que está cubierto.
