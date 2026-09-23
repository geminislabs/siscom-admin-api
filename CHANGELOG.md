# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

> **Nota.** Lo que sigue arrastra entradas de varias versiones ya liberadas que
> nunca se movieron a su sección. Se dejan aquí a propósito: atribuirlas exigiría
> saber qué salió en cada tag anterior a `1.25.0`, y adivinarlo produciría un
> historial falso. Las de `1.25.0`, `1.26.0`, `1.27.0`, `1.27.1`, `1.28.0`, `1.29.0`, `1.29.1`,
> `1.30.0`, `1.30.1`, `1.31.0`, `1.32.0`, `1.32.1` y `1.32.2` sí se
> repartieron, derivadas de `git log <tag-anterior>..<tag>`.

### Changed

- **`PATCH /internal/users/{id}/status` reconcilia el proveedor siempre, aunque la fila ya esté en
  ese estado.** Antes cortaba en seco y respondía `proveedor_sincronizado: true` **sin haber
  hablado con nadie**, para ahorrar tráfico contra Cognito
  - El razonamiento confundía dos cosas: refrescar una pantalla es un `GET`, no un `PATCH`. Ese
    tráfico nunca llegaba por aquí
  - Y el atajo tenía un fallo peor que el tráfico que ahorraba: **cuando la fila y el proveedor
    divergen, era lo único que podía reconciliarlos y se negaba a intentarlo**. Pasó en producción
    el 22/09: seis bajas escribieron `INACTIVE` en la base y fallaron contra Cognito por un permiso
    de IAM que faltaba (`AdminDisableUser`, sobre el rol `EC2-SISCOM-SES-Role`). Al reintentar, el
    endpoint respondía «sin cambio, todo sincronizado» —falso sobre un estado roto— y hubo que
    rodearlo a mano con un ciclo `ACTIVE`/`INACTIVE`
  - El test que lo cubría afirmaba justo lo contrario, así que se sustituye por su inverso, más
    uno para el caso de divergencia que se dio de verdad
- **«No pude deshabilitar» y «no había nada que deshabilitar» dejan de ser lo mismo**, y el
  significado depende de la dirección
  - Hacia `INACTIVE`, que no exista credencial **es** el estado deseado: sin credencial no hay
    forma de autenticarse. Se reporta como sincronizado, porque decir lo contrario mandaría a
    alguien a buscar una credencial viva que no existe
  - Hacia `ACTIVE` **no** lo es: la fila diría que la persona está activa y no podría entrar. Eso
    es divergencia real, y el arreglo es crearle credencial, no reintentar
  - Medido el 22/09: dos de los siete huérfanos —`borrar@hotmail.com` y `kibewac890@emaxasp.com`,
    el segundo sin un solo inicio de sesión— devolvían `UserNotFoundException` en las dos
    direcciones
- `GET /internal/accounts` deja de usar `DISTINCT ON` (Postgres-only): el owner se resuelve con `GROUP BY` + `min(email)` para que el query sea válido en SQLite (CI) y en Postgres
- Middleware HTTP que convierte excepciones no manejadas en JSON `{"detail":"Internal server error"}` **dentro** de CORS, para que un 500 no se reporte en el browser como error de CORS
- Engineering foundation (PR-1): blocking CI (`quality` + `security` jobs)
- Soft foundations (PR-2): `.devcontainer/`, `docs/security/threat-model.md`, GitHub issue templates, process ADRs (002, 003)
- Quality gates (PR-3): `CODEOWNERS`, `dependabot.yml`, `docs/GOVERNANCE.md`, OSV-Scanner, `osv-scanner.toml`
- Coverage floor (65% on `app/`) via `pyproject.toml`

- `scripts/gitleaks-scan.sh`, `scripts/pip-audit-scan.sh`, `scripts/osv-scan.sh`, `scripts/setup.sh`
- `.pre-commit-config.yaml` (Ruff, Black, hygiene hooks)
- `AGENTS.md`, `CONTRIBUTING.md`, `SECURITY.md`, `docs/RELEASE.md`
- `.editorconfig`, `.python-version`, `.gitleaks.toml`
- GitHub pull request template
- `make validate`, `make scan-secrets`, `make audit-deps`
- Docs: `docs/api/teams.md` documenta los endpoints de teams, miembros, reglas de visibilidad, invitaciones, emergencias y snapshots internos ya presentes en `develop`
- Docs: `docs/api/INDEX.md` incorpora teams y el set completo de `/mobility/devices` y `/mobility/locations` al índice y al mapa de rutas
- Contrato Kafka de `user-devices-updates`: el payload pasa al envelope de control (`event_id`, `event_type`, `entity`, `organization_id`, `data`). La key es el UUID de la fila `user_devices.id`, no el token. **Ya no se envía `unit_id`**. `alert-distributor` tiene que consumir este contrato (deploy de consumers **antes** que esta API)
- Deploy: `deploy.yml` y docker-compose reciben `KAFKA_UNIT_DEVICES_UPDATES_TOPIC` y `KAFKA_USER_UNITS_UPDATES_TOPIC`. Si las GitHub vars del environment `test` no existen, el workflow usa los defaults del código
- Test harness: SQLite keeps JSONB operators (`.astext`) via compile hook; pytest env defaults in `conftest` for runs without `.env`
- CI: Ruff, Black, pytest, and Docker build are blocking (removed `|| true`)
- Deploy workflow: quality gates delegated to CI; deploy only builds and ships on tags
- Deploy workflow: `alembic upgrade head` corre en un contenedor efímero (misma red y `.env`) antes de levantar el contenedor nuevo
- Test harness: session-scoped SQLite metadata patch, GAC auth in `authenticated_client`, telemetry/sims isolation fixes
- Minimum Python version raised to **3.12** (CI, Docker, Black/Ruff targets, docs)
- Dependency security bumps: `cryptography`, `idna`, `python-multipart`, `starlette`, `pyseto`
- Dependency security bumps: `cryptography` 48.0.1 → 50.0.0 (PYSEC-2026-3552/3553/3554), `kafka-python` 2.3.0 → 2.3.2 (PYSEC-2026-2190/2191), `pyasn1` 0.6.3 → 0.6.4 (PYSEC-2026-3455/3456/3457)
- `scripts/pip-audit-scan.sh` ignora `PYSEC-2026-1325` (`ecdsa`, transitivo vía `python-jose`): no hay versión corregida y no es alcanzable — solo verificamos JWT con RS256. Mismo riesgo ya aceptado en `osv-scanner.toml`
- Gitleaks scans working tree only (`--no-git`); doc placeholders sanitized

### Fixed

- **`Subscription.is_active()` lanzaba `TypeError` en cuanto una suscripción entraba en gracia.** `grace_until` es `TIMESTAMP WITH TIME ZONE` y `expires_at` es `TIMESTAMP` sin zona, mientras que `utcnow()` devuelve naive a propósito: comparar `grace_until > utcnow()` da `can't compare offset-naive and offset-aware datetimes`. Es el camino que recorre el código de cobranza al fallar un cobro. No se veía porque los tests corrían sobre SQLite, que devolvía todo naive. Se normaliza en la frontera de comparación con `as_naive_utc()`, siguiendo el patrón que ya usaba `access_control._aware`

- Reasignar un tracker a otra org/unidad no actualizaba caches de `event-processor` / `alert-distributor`: no había evento de control. Quien recibía el push seguía siendo el dueño anterior hasta reiniciar esos servicios
- Auth: las peticiones sin header `Authorization` (o con esquema distinto de Bearer) responden `401` con `WWW-Authenticate: Bearer` en lugar del `403` por defecto de `HTTPBearer`. Los clientes iOS/Android disparan el refresh de token solo con `401`
- `billing.py`: query devices by `device_id` (not legacy `Device.id`) — 8 billing unit tests re-enabled
- User-commands list/sync tests re-enabled on SQLite JSONB paths (2 tests)
- Auth: una caída de Cognito (JWKS inalcanzable y sin caché) ya no se presenta como `401`. En los endpoints de doble autenticación el error 5xx se propaga en vez de caer al camino PASETO y acabar respondiendo `401`, que mandaba al cliente a reautenticarse contra un problema que ninguna credencial arregla — y convertía la caída en una tormenta de peticiones sobre esta API

### Notes

- 24 tests still skipped (device status flow, orders invoice fixture, legacy DeviceService API, device activation) — follow-up PRs

### Security


- Gitleaks + Semgrep + pip-audit + OSV-Scanner in CI `security` job
- `POST /api/v1/mobility/locations` y `/batch` exigen JWT y validan que el `device_id` pertenezca a un dispositivo activo del usuario autenticado. Antes aceptaban cualquier `device_id` sin autenticación, lo que permitía inyectar ubicaciones de terceros al tópico de Kafka
- PASETO: los tokens de compartir ubicación se firman con `SHARE_LOCATION_KEY_B64`, una clave dedicada, en lugar de con `PASETO_SECRET_KEY`. El verificador de esos tokens vive en siscom-api; entregarle la clave de servicio le permitía firmar tokens `internal-*` y llamar a la API interna como administrador. Sin la clave nueva configurada, `/units/{id}/share-location` responde `503` en vez de degradar a la clave de servicio (ver ADR-004)
- `decode_any_token` se elimina: probaba las dos claves contra el mismo token, de modo que un token de compartir ubicación podía acabar aceptado donde se esperaba uno de servicio
- `scripts/paseto_key_fingerprint.py` imprime la huella SHA-256 (12 hex) del material de clave **efectivo**, para comparar entre servicios sin transmitir la clave
- Telemetría: el acceso a un dispositivo deja de ser un booleano y pasa a ser un conjunto de rangos temporales autorizados. Un dispositivo reasignado a otra organización deja de ser legible por la anterior fuera de la ventana en que estuvo asignado
- El resolver de alcance es explícito por sujeto (`ScopeSubject`): `accessible_device_ids`, que decidía a partir del usuario implícito, se elimina

## [1.36.0] - 2026-09-22

**Migraciones.** **Ninguna.** Revisión `029_estado_de_usuario` antes y después; la señal correcta
es la **ausencia** de `Running upgrade`.

**Rollback.** Redesplegar `v1.35.0` **reabre el agujero**. Si hay que revertir por otra razón,
revertir a `v1.35.0` deja el plano de control abierto otra vez: preferible arreglar hacia delante.

**Por qué sale sola y cuanto antes.** Es un arreglo de seguridad, y la `v1.35.0` —desplegada hoy
mismo— añadió la ruta que más daño hacía. Va sin nada más dentro para que el despliegue no tenga
que sopesar otros riesgos.

**Qué comprobar después.** Que GAC sigue funcionando. Usa PASETO por `getInternalToken()` contra
`/internal/tokens/app` de `gac-api`, que emite `service: gac` / `role: GAC_ADMIN`, así que su
camino no cambia. **Si algo de GAC empieza a dar 403**, es que alguna llamada iba con credenciales
de usuario y hay que darle su propia ruta — no reabrir ésta.

### Security

- **El plano de control estaba abierto a cualquier usuario autenticado.** `get_auth_cognito_or_paseto`
  intenta Cognito primero y, si el token es válido y el usuario existe, concede acceso **sin mirar
  ningún rol**: `required_service` y `required_role` se aplicaban sólo al camino PASETO. Cualquiera
  que pudiera iniciar sesión en Nexus podía llamar a las **20 rutas de escritura** de `/internal/*`
  — desactivar a cualquier usuario, suspender organizaciones, cancelar suscripciones, borrar planes
  - **Verificado por ejecución**: un usuario normal recibió `200` de
    `PATCH /internal/users/{id}/status` y dejó a la víctima en `INACTIVE`
  - Se cierra con `get_auth_solo_servicio`, que **sólo acepta PASETO**, en los ocho módulos internos
  - **`trips` y `commands` no se tocan, a propósito**: declaran el mismo `required_service` pero son
    endpoints de usuario — `nexus-web` llama a `/units/{id}/trips` con token de Cognito y los
    móviles también. Cerrar la factory entera habría roto la pantalla de viajes
  - **El test que debía cubrirlo preguntaba lo que no era**: mandaba la petición *sin cabecera* y
    comprobaba el 401. La pregunta no era «¿rechaza a quien no trae token?» sino «¿rechaza a quien
    trae **otro** token?». Ahora existen las dos
  - Detalle completo en `docs/security/plano-de-control-abierto.md`

## [1.35.0] - 2026-09-22

**Migraciones.** **Ninguna.** La revisión sigue en `029_estado_de_usuario` antes y después: la
señal correcta en el log del despliegue es la **ausencia** de `Running upgrade`.

**Rollback.** Redesplegar `v1.34.0`. No hay esquema que revertir. Lo que se pierde al revertir es
la única vía por API para tocar a los huérfanos — se vuelve a depender de SQL a mano.

**Minor.** Dos endpoints nuevos, `GET /internal/users` y `PATCH /internal/users/{id}/status`.
Aditivo: nada de lo que existía cambia de forma ni de conducta.

**Para qué se despliega esta release, en concreto.** Para poder desactivar por API a **seis de los
siete huérfanos** —decididos uno por uno el 22/09 con sus datos delante: ninguno tiene unidades,
dispositivos ni equipos, y ninguno tiene una organización viva a la que ser reasignado—. El
séptimo, `fer.garrido.chvz@gmail.com`, es de Geminis y **se arregla, no se desactiva**; su destino
sigue sin decidirse porque no tiene ninguna cuenta con organizaciones vivas.

**Qué comprobar después.** El reparto de `users.status` pasa de `ACTIVE: 23` a
`ACTIVE: 17, INACTIVE: 6` **sólo cuando se ejecuten las bajas**, que es un paso aparte y manual.
Si cambia antes, o cambia de otra forma, hay un camino marcando filas sin que nadie lo pida.

### Added

- **Superficie interna de usuarios para GAC** — `GET /internal/users` y
  `PATCH /internal/users/{id}/status`, con token PASETO de servicio (`gac` / `GAC_ADMIN`)
  - **Direcciona al usuario por su id y no pasa por organización, y ése es el punto.** Los siete
    huérfanos **no se pueden tocar** por `DELETE /organizations/{org}/users/{id}`: su
    `organization_id` apunta a una organización que no existe, así que `_verify_org_access` falla
    antes de llegar al usuario. El endpoint que la `v1.34.0` creó justo para desactivar gente no
    puede desactivarlos
  - `orphaned=true` promueve a endpoint el contador (4) del runbook de la 029, que hasta ahora era
    SQL suelto
  - El refuerzo en el proveedor va **después** del commit y **se informa en la respuesta**
    (`proveedor_sincronizado`) en vez de tragárselo: permite a GAC enseñar «desactivado, pero la
    credencial sigue viva» en vez de mentir
  - **El harness resultó ser más estricto que producción.** El modelo declara
    `ForeignKey("organizations.id")` en `users.organization_id` y `create_all()` la crea; el
    esquema productivo **sólo tiene un índice**. Sin quitar esa restricción en la prueba, el caso
    que este endpoint existe para resolver **no se puede escribir como test** — la base de pruebas
    lo prohíbe y la de verdad lo contiene siete veces
- **Un test que 1 de cada 63 veces no probaba nada.**
  `test_decode_share_token_returns_none_for_tampered_token` sustituía el carácter `token[-3]` pero
  elegía el reemplazo mirando `token[-1]`: cuando el antepenúltimo ya era una `X`, `bad` salía
  **idéntico al original** y el test decodificaba un token intacto. Tasa medida sobre 200 000
  tokens simulados: **1,57 %**. Tumbó la CI del PR #100, que no tenía nada que ver
  - Además del arreglo, el test ahora **afirma que manipuló algo** (`assert bad != token`) antes de
    afirmar nada más. Sin esa línea puede volver a quedarse sin tocar el token y nadie se entera
    hasta que falla, meses después, en una corrida ajena
- **CI: adiós a Node 20.** `actions/checkout`, `actions/setup-python` y `actions/upload-artifact`
  pasan de `v4` a `v7`. GitHub ya forzaba esas tres a correr en Node 24 y lo avisaba en cada
  corrida; las versiones nuevas lo declaran. De paso se unifican las `checkout`, que convivían en
  `v4` y `v6` en el mismo repositorio
  - **`appleboy/scp-action` y `appleboy/ssh-action` se quedan como están**, a propósito: el log del
    workflow de despliegue **no emite ningún aviso**, así que no están afectadas. Viven en el
    camino del despliegue y sólo se validan desplegando — no hay razón para arriesgarlo por un
    aviso que no existe

## [1.34.0] - 2026-09-22

**Migraciones.** **Ninguna.** La revisión sigue en `029_estado_de_usuario` antes y después: la
señal correcta en el log del despliegue es la **ausencia** de `Running upgrade`. Si aparece, parar.

**Rollback.** Redesplegar el tag anterior (`v1.33.0`). No hay esquema que revertir. Lo que sí
vuelve es el *fallback* de `is_master` y la imposibilidad de reinvitar a un usuario dado de baja.

**Por qué minor, y por qué el método de §23 no lo habría dicho.** El contrato OpenAPI es
**estructuralmente idéntico** al de la `1.33.0`: comparando `app.openapi()` en un worktree de cada
rama, la única diferencia en 25 985 líneas es el texto de una descripción. Y aun así es minor,
porque lo que cambia es **conducta**: `invite_user` acepta un caso que antes devolvía 400, y
`DELETE …/users/{id}` gana un efecto que antes no tenía. La comparación de OpenAPI detecta
rupturas de forma y es **ciega a los cambios de comportamiento** — aplicada mecánicamente, esto se
habría etiquetado como patch.

**Qué mirar en este despliegue, además de lo de arriba.** Es la primera release con código capaz
de escribir `users.status`. Hoy el reparto es `ACTIVE: 23`; conviene volver a correr la consulta
del punto 5 del runbook unos días después. Si aparece algún `INACTIVE` que nadie pidió, hay un
camino marcándolo sin querer.

### Changed

- **El código que usa `users.status` — la mitad *contract* de la `029`.** Cierra el callejón sin
  salida que ya ocurría en producción: se sacaba a alguien de la organización, la fila de `users`
  sobrevivía intacta, y al reinvitarlo `invite_user` la encontraba y respondía 400 sin que hubiera
  ningún endpoint capaz de resolverlo
  - `DELETE /organizations/{org}/users/{user_id}` **marca la fila `INACTIVE`** además de borrar la
    membresía, y sólo cuando la organización es la suya — alguien puede ser miembro de varias. La
    fila **no se borra**: veinte FK la referencian, varias en cascada
  - `invite_user`, `resend_invitation` y `accept_invitation` dejan de rechazar a un usuario
    `INACTIVE`. `accept_invitation` **reactiva esa misma fila**, con su id: es lo que conserva sus
    unidades y dispositivos, y lo único posible — los índices de la 028 no filtran por estado, así
    que Postgres rechazaría una fila nueva con el mismo correo
  - **El handle de la reactivación sale de `external_id`, no del correo.** Hoy coinciden; con
    handles UUID (rebanada B2) dejarán de coincidir, y reconstruirlo fallaría en silencio
  - `IdentityProvider` gana `deshabilitar()` y `habilitar()` (`admin_disable_user` /
    `admin_enable_user`). Es **refuerzo, no el dato**: la fuente de verdad es `users.status`, y por
    eso el fallo del proveedor se registra pero no tumba la baja
- **Se borra el *fallback* de `is_master`** en `OrganizationService.get_user_role`. Era una segunda
  fuente de verdad sobre el rol, y tenía un fallo propio: a un master al que le borraban la
  membresía no se le quitaba el rol. Lo autorizó una medida — el contador (a) del runbook de la
  029 dio `0` contra producción el 21/09
- **CI: `cancel-in-progress`.** Un push nuevo cancela la corrida anterior de la misma rama, que
  juzga código ya reemplazado. **Excepto en `master`**, donde la corrida es la que valida el commit
  que se va a etiquetar
- **El harness de tests deja de sondear Kafka al arrancar la app.** `_stub_kafka_producers()` ya
  silenciaba los seis productores, pero `check_kafka_accessibility()` vive en el `lifespan` y no es
  una dependencia, así que ningún `dependency_overrides` lo alcanzaba — y `client` abre
  `TestClient(app)` **por test**. Son 245 de los 849 tests, y en CI cada uno costaba 3,02 s
  clavados (`api_version_auto_timeout_ms: 3000`): **740 s de los 780 s** del paso de tests.
  Verificado con un sondeo lento simulado: los mismos 7 tests pasan de 22,00 s a 0,74 s

## [1.33.0] - 2026-09-21

**Migraciones.** **Ninguna.** La revisión sigue en `029_estado_de_usuario` antes y después. La
señal correcta en el log del despliegue es la **ausencia** de `Running upgrade`; si aparece, algo
va mal y hay que parar.

**Rollback.** Redesplegar el tag anterior. No hay esquema que revertir.

**Por qué minor y no patch.** El contrato OpenAPI cambia, y de forma aditiva: un campo opcional
nuevo en `RefreshTokenResponse`. Comparado generando `app.openapi()` en un worktree de cada rama,
el mismo método que cerró la `1.30.1` como patch — ahí el contrato era byte-idéntico y aquí no.

### Added

- **`POST /auth/refresh` devuelve `refresh_token`** cuando el proveedor da uno nuevo. Hoy este pool
  no rota (`RefreshTokenRotation: null`), así que el campo sale `null` y **nada cambia para ningún
  cliente**
  - Es el **paso 1 del orden de §24, y va antes de activar la rotación, no después**. Con rotación,
    Cognito devuelve un refresh token nuevo en cada renovación y el anterior caduca pasado el
    periodo de gracia. El endpoint lo tiraba: `Sesion.refresh_token` ya venía del proveedor desde
    la `1.30.1`, pero ni el código lo copiaba ni el schema lo declaraba. Activar la rotación así
    manda a todo el mundo a la pantalla de login, sin nada en los logs que lo explique
  - `nexus-web` ya guarda el token si viene (`setSession()`); iOS y Android tendrán que hacerlo
    cuando arreglen su refresh, que hoy devuelve 422
  - Dos tests, y el del token rotado **verificado quitando la línea del arreglo**: falla con
    `AssertionError` y vuelve a verde al restaurarla

### Changed

- **CI: `pytest` reporta las 25 pruebas más lentas** (`--durations=25`). El job `quality` tarda
  ~14,5 min y nadie sabía en qué. Medido sobre la corrida `35646430146`: de 874 s, **786 s son el
  paso de tests** y todo lo demás suma 88 s. El primer desglose dice que **no hay ningún test
  lento** — hay ~250 pagando un coste fijo de 3,02 s en `setup`, en módulos que no comparten nada.
  El mismo conjunto tarda 23 s en local, así que el coste es del entorno de CI y no de los tests.
  Queda abierto qué lo produce

### Fixed

- `docs/runbooks/desplegar-estado-de-usuario.md` deja de decir «No se ha desplegado» y **anota sus
  seis contadores**, medidos contra producción: (a), (b), (c) y el relleno en `0`, siete huérfanos,
  y `ACTIVE: 23` sin otros valores
  - **(a) = 0 es lo que autoriza borrar el *fallback* de `is_master`** en
    `OrganizationService.get_user_role`, que abre el release siguiente
  - (4) junto a (5) dicen algo que «los siete huérfanos» dicho suelto escondía: son **siete sobre
    veintitrés**, casi un tercio de la tabla

## [1.32.2] - 2026-09-21

**Migraciones.** Una: `029_estado_de_usuario` — **la misma que la `1.32.0` y la `1.32.1`
anunciaron y no llegaron a aplicar**. Cabeza: `028_identidad_esquema` → `029_estado_de_usuario`.

**Rollback.** Basta redesplegar el tag anterior: la migración es aditiva y el código de `1.31.0`
ignora la columna que no conoce.

### Fixed

- **El relleno excluye las organizaciones inexistentes.** El despliegue de la `1.32.1` falló en
  400 ms con `ForeignKeyViolation`: la organización del primer usuario del relleno **no existe en
  `organizations`**
  - **La premisa era falsa.** Se había medido «siete usuarios con `is_master` y sin membresía
    OWNER» y se concluyó que eran **masters heredados**. Al medir los huérfanos salieron
    **exactamente los mismos siete**. La causa es circular: **no tienen membresía porque su
    organización no existe** — `organization_users.organization_id` tiene FK a `organizations`, así
    que esa fila nunca pudo crearse. No son heredados: son **huérfanos**
  - **El relleno inserta cero filas**, y nunca iba a insertar otra cosa. Se conserva con el
    `EXISTS` porque es el invariante correcto y hará lo suyo si algún día aparece un master con
    organización real y sin membresía
  - **El *fallback* de `is_master` se puede borrar sin relleno ninguno**: lo único que sostiene son
    huérfanos, a los que da «OWNER de una organización que no existe». Al quitarlo pasan a `None`,
    que no es menos acceso — es el mismo, dicho con verdad
  - **Hallazgo colateral, y es el que más pesa**: `users.organization_id` **no tiene clave foránea
    en producción**. El DDL sólo declara un índice; el modelo sí la declara. Es deriva que el
    comparador no ve porque mira columnas y no restricciones — sobre **la columna de la que cuelga
    la autorización de 62 endpoints**. Añadirla exige resolver antes los siete huérfanos
  - Test `test_master_con_organizacion_inexistente_no_tumba_la_migracion`, **verificado quitando el
    `EXISTS`**: reproduce el `ForeignKeyViolation` exacto de producción
- **Corregida una afirmación falsa** que entró con la `1.32.0`: decía que una de las siete era la
  cuenta de Jesús y que quitar el *fallback* sin rellenar le habría costado el OWNER de su
  organización. Su organización no existe, así que el *fallback* sólo le daba OWNER de algo que no
  está. Corregido en la migración, el runbook y este changelog
- **El runbook, coherente de punta a punta.** Los contadores llevan el `EXISTS`; el del relleno pasa
  de «debería ser 7» a **debe ser 0**; y se añaden dos informativos — los huérfanos (que **no** son
  cero: son 7 y esta release no los toca) y el reparto de `status`

## [1.32.1] - 2026-09-21

> ### ⚠️ Etiquetada, pero **tampoco llegó a producción**
>
> Esta vez no se colgó: falló en **400 ms** con `ForeignKeyViolation` sobre
> `organization_users_organization_id_fkey`. El `lock_timeout` hizo su trabajo —el `ALTER`
> tomó su bloqueo al instante— y lo que salió fue un problema distinto y anterior: **siete
> usuarios cuya organización no existe**. Producción siguió en `v1.31.0` con el esquema en
> `028`.
>
> **Lo que esta versión describe se liberó realmente en la `1.32.2`.**

**Migraciones.** Una: `029_estado_de_usuario` — **la misma que la `1.32.0` anunciaba y no llegó a
aplicar**. Cabeza: `028_identidad_esquema` → `029_estado_de_usuario`.

**Rollback.** Idéntico al de la `1.32.0`: basta redesplegar el tag anterior, porque la migración es
aditiva y el código de `1.31.0` ignora la columna que no conoce.

> **Este downgrade no es del todo simétrico, y es deliberado.** Quita `users.status` y su `CHECK`,
> pero **no borra las siete membresías `owner` que el relleno creó**. Hay un test que lo fija.

### Fixed

- **La `029` ya no puede colgarse esperando un bloqueo.** El despliegue de la `1.32.0` se quedó
  **9 m 42 s** en el `ADD COLUMN` hasta que el canal SSH se rindió. `ALTER TABLE` necesita
  `ACCESS EXCLUSIVE` sobre `users`, y `users` se lee en **cada petición autenticada**
  (`deps.py` busca por `cognito_sub`): si algo tiene la tabla tomada el ALTER espera, y **mientras
  espera, los lectores que llegan después se encolan detrás de él**. Una operación que en PG15 es de
  metadatos —sin reescritura de tabla— se convirtió en diez minutos de autenticación degradada
  - `SET LOCAL lock_timeout = '10s'` y `SET LOCAL statement_timeout = '5min'` al principio del
    `upgrade`. El peor caso pasa de diez minutos de cola a **un fallo de diez segundos que no toca
    nada**, y cuyo error **nombra el bloqueo** — el diagnóstico que la primera vez hubo que ir a
    buscar a mano y ya no estaba
  - **En la migración y no en `deploy.yml`**, a propósito: así viaja con ella y protege también a
    quien la corra a mano para repararla en caliente. Un guardián general en el workflow es buena
    idea y es otro cambio
  - **Verificado de paso que producción es PostgreSQL 15** (`timescale/timescaledb:2.15.1-pg15`).
    Descarta la hipótesis de reescritura de tabla y deja la contención de bloqueo como única
    explicación razonable — que **sigue sin estar probada**: lo que lo probaría (`pg_locks` durante
    el atasco) se perdió al morir el intento. El `lock_timeout` es justamente lo que la probará
  - Se edita la `029` **en sitio** y no se añade una `030`: nunca llegó a aplicarse en ningún
    entorno

## [1.32.0] - 2026-09-21

> ### ⚠️ Etiquetada, pero **nunca llegó a producción**
>
> Su despliegue **no falló: se colgó.** La migración se quedó 9 m 42 s esperando el
> `ACCESS EXCLUSIVE` sobre `users` hasta que el canal SSH se rindió por timeout, y la
> transacción de alembic revirtió entera. Producción siguió en `v1.31.0` con el esquema en
> `028_identidad_esquema`, sin que el contenedor se tocara: las migraciones corren **antes**
> de sustituirlo.
>
> **Lo que esta versión describe se liberó realmente en la `1.32.1`.** Se conserva la sección
> porque el tag existe: es más honesto que un `v1.32.0` publicado no aparezca como versión
> fantasma el día que alguien lo busque en un `/health`.

**Migraciones.** Una: `029_estado_de_usuario`. Cabeza: `028_identidad_esquema` →
`029_estado_de_usuario`.

**Rollback.** Basta redesplegar el tag anterior: la migración es aditiva (expand/contract), así que
el código de `1.31.0` convive con el esquema nuevo — ignora la columna que no conoce. Si además
hiciera falta revertir el esquema, **antes** de desplegar el tag viejo, porque el archivo de la
migración vive en la imagen nueva:

```bash
docker run --rm --network siscom-network --env-file .env \
  siscom-admin-api:latest alembic downgrade 028_identidad_esquema
```

> **Este downgrade no es del todo simétrico, y es deliberado.** Quita `users.status` y su `CHECK`,
> pero **no borra las siete membresías `owner` que el relleno creó**: materializan un rol que esas
> personas ya tienen hoy a través del *fallback* de `is_master`, y borrarlas las dejaría peor que
> antes de la migración. Está fijado con un test para que nadie añada el `DELETE` «por simetría».

**Contrato.** El OpenAPI es **byte-idéntico** al de `v1.31.0`, comparado generando `app.openapi()`
en un *worktree* de cada punto. Es minor y no patch por el cambio de esquema, no por el de contrato:
ningún cliente ve nada distinto.

**Verificación después de desplegar.** Las tres señales del paso 6 de `docs/RELEASE.md`, más los tres
contadores de `docs/runbooks/desplegar-estado-de-usuario.md`. El primero es el que importa: **cuando
dé 0, el *fallback* de `is_master` ya no sostiene a nadie y se puede borrar** — que es lo que
desbloquea la rebanada de código siguiente.

### Added

- **`users.status`** (migración `029_estado_de_usuario`), `text NOT NULL DEFAULT 'ACTIVE'` con `CHECK (status IN ('ACTIVE','INACTIVE'))`. Es la mitad *expand*: ningún modelo la lee todavía. Destraba un fallo **que ya ocurre en producción** — quitar a alguien de una organización borra la membresía pero deja la fila de `users`, así que **volver a invitarlo responde 400 y no hay salida por la API**: no existe endpoint que borre un usuario y no había estado que marcar
  - **Relajar la comprobación no era una opción.** Los índices de la `028` (`uq_users_marca_correo`, `uq_users_correo_marca_por_defecto`) no filtran por estado, así que aunque la aplicación dejara pasar el alta, Postgres la rechaza. La respuesta correcta es **reactivar la fila**, no crear otra — y así se conserva el handle de Cognito, que es inmutable y sigue siendo válido
  - **Sólo dos valores, a propósito.** Añadir `SUSPENDED` o `PENDING` ahora sería sembrar códigos sin semántica acordada, lo mismo que la `027` evitó al no sembrar `self_signup_mode`
  - **Relleno de las membresías `owner` de los masters heredados.** `OrganizationService.get_user_role` tiene un *fallback* (`organization.py:78-81`) que devuelve OWNER a un `is_master` sin membresía — segunda fuente de verdad, y con un fallo propio: **a un master al que le borran la membresía no se le quita el rol**. Para poder borrar ese *fallback* en el release siguiente, quien dependa de él necesita su membresía explícita. Medido contra producción el 20/09: **siete usuarios, los siete sin ningún evento `org_user_removed`** — masters heredados, ninguno removido a propósito
  - El `INSERT` **excluye a quien tenga un `org_user_removed` en `account_events`** aunque hoy eso no deje fuera a nadie: hace la migración auto-correctiva si alguien quita a un master entre la medición y el despliegue. Y su `NOT EXISTS` de membresía **no filtra por rol**, o crearía una segunda fila para quien ya tiene membresía con otro rol y violaría `uq_org_user`
  - **El `downgrade` quita la columna y deja el relleno**, decidido y no olvidado: esas membresías materializan un rol que esas personas ya tienen hoy, y borrarlas las dejaría peor que antes de la migración. Fijado con un test para que un `DELETE` «por simetría» se vea en CI
  - Runbook: `docs/runbooks/desplegar-estado-de-usuario.md`. Contexto y decisiones: §26 del documento de arquitectura
- **Auditoría de dependencias por tiempo** (`.github/workflows/dependency-audit.yml`), **lunes y jueves**, sobre `master` y `develop`. `ci.yml` sólo corre con `push` y `pull_request`, así que **un aviso publicado entre dos PRs deja el repositorio vulnerable sin que nadie lo sepa** — es como se destaparon los dos CVE de `anyio` el 18/09: porque un PR de otra cosa los encontró, no porque nadie estuviera mirando. El mismo hueco existía en `nexus-web-page`, donde llegó a ser de trece días
  - **Sólo se programa el escaneo de dependencias.** Gitleaks y semgrep son función del código y no pueden ponerse rojos solos: correrlos por reloj repetiría el mismo veredicto y enseñaría a ignorar los correos de fallo. CodeQL ya tiene su propio `schedule` y no se toca
  - Corre `pip-audit-scan.sh` y `osv-scan.sh` **tal cual**, para que las listas de riesgos aceptados —el `--ignore-vuln` de `ecdsa` y `osv-scanner.toml`— no se dupliquen aquí y se desincronicen
  - **Lunes y jueves, no diario.** Cron no sabe expresar «cada 72 horas»: `*/3` sobre el día del mes reinicia el contador en cada cambio de mes —del 31 al 1 pasa un día, no tres— y puede caer en fin de semana, que es una alerta que nadie mira hasta el lunes. Con lunes y jueves el hueco máximo son 4 días y siempre cae en día laborable
  - **Revisa sólo la rama por defecto**, no las dos. La primera versión llevaba matriz sobre `master` y `develop`, y **CodeQL la rechazó con dos alertas altas de `cache-poisoning`**: un workflow programado corre con los privilegios de la rama por defecto, así que hacer checkout de `develop` y ejecutar sus `scripts/*.sh` daba a código de una rama menos protegida acceso de escritura a la caché de `master`. Se pierde poco — `develop` ya lo escanea `ci.yml` en cada push y en cada PR, y en el hueco que este workflow viene a tapar `develop` no cambia

## [1.31.0] - 2026-09-18

**Migraciones.** Ninguna. La cabeza sigue en `028_identidad_esquema`, que entró con `1.30.0`.

**Rollback.** Redesplegar el tag anterior: no toca el esquema, así que no hay nada que revertir
en la base ni orden que respetar.

**Orden entre repositorios.** `nexus-web-page v1.16.1` va **antes** que esta release, y ya está
desplegada. Las dos son seguras en cualquier orden, pero sólo así no hay ventana: la web ya sabe
adoptar la sesión nueva que este release empieza a mandar, de modo que cambiar la contraseña no
echa a nadie al login.

**Verificación después de desplegar.** Entrar desde dos navegadores, cambiar la contraseña en uno y
confirmar que el otro se cae. Es la propiedad entera de esta release en treinta segundos — y una
propiedad que hasta hoy no existía en ninguna parte del sistema.

### Security

- **Cambiar o restablecer la contraseña ahora cierra todas las sesiones.** Hasta ahora sólo lo hacía `POST /auth/logout`: `PATCH /auth/password` y `POST /auth/reset-password` cambiaban la credencial y dejaban vivas las sesiones anteriores. Con **refresh tokens de 90 días** en el pool productivo, eso significaba que quien sospechaba que le habían robado la cuenta cambiaba su contraseña y el intruso seguía renovando sesión durante meses — y el único gesto que lo cortaba era un logout, que es justo lo que no hace quien no sabe que lo hackearon
  - La interfaz gana `revocar_sesiones_de(handle)`, la variante **administrativa**: los dos sitios donde importa revocar no tienen access token que ofrecer — el restablecimiento no está autenticado, y el cambio sí lo está pero quien lo pide es a quien no hay que echar
  - **Qué corta y cuándo, sin prometer de más**: el plano de datos al instante (borrar el alcance en Valkey invalida los data tokens ya emitidos), y el de control en cuanto caduque el access token — revocar en el proveedor mata los refresh tokens, pero los access tokens ya emitidos siguen válidos hasta su vencimiento, que en este pool se mide en minutos
  - Se revoca **primero el plano de datos**, igual que en el logout y por la misma razón: si el proveedor fallara, la sesión del mapa ya está cortada
  - **Si la revocación falla, el endpoint lo dice.** La contraseña ya está cambiada a esas alturas, así que responder 200 sería mentir sobre lo que se consiguió: devuelve 500 diciendo que hay que cerrar sesión en los otros dispositivos
- **`PATCH /auth/password` devuelve una sesión nueva**, en campos opcionales que se añaden a su respuesta. La revocación no distingue el dispositivo de quien cambia la contraseña del de nadie, así que sin esto hacer lo correcto te costaba volver a entrar. Se reautentica **después** de revocar —o la sesión nueva caería con las demás— y es *best effort*: si falla, la contraseña ya cambió y las sesiones ya se cortaron, así que se responde igual sin credenciales
- **`anyio` 4.13.0 → 4.14.2** (CVE-2026-63374 y CVE-2026-64847). Llega por `starlette`, `httpx` y `watchfiles`, así que **viaja en la imagen de producción**. Los dos avisos se publicaron después de la última build verde, así que la CI llevaba en rojo sin que nadie tocara el repositorio — el mismo patrón que `nanoid` y `fast-uri` en `nexus-web-page`
  - El primero es el que importa aquí: en conexiones TLS hacia dominios internacionalizados, un atacante que ya haya secuestrado la conexión puede presentar un certificado legítimo de la versión IDNA 2003 del dominio y hacer que valide
  - El segundo bloquea a un *worker* de pool de procesos que escriba demasiado a `stderr`, porque `anyio` no drena esa tubería
  - `pip check` limpio y `pip-audit` deja de reportarlos

## [1.30.1] - 2026-09-11

**Migraciones.** Ninguna. La cabeza sigue en `028_identidad_esquema`, que entró con `1.30.0`.

**Rollback.** Redesplegar el tag anterior: no toca el esquema, así que no hay nada que revertir en
la base ni orden que respetar. Los índices y los `CHECK` que esta release añade a los modelos son
declarativos —los crea `create_all()` en el harness de tests, para que imponga la misma unicidad
por marca que producción—; en producción ya existían desde la `028` y esta release no ejecuta un
solo DDL.

**Antes de desplegar.** Correr los tres contadores del paso 3 de
`docs/runbooks/desplegar-identidad.md`. A partir de esta release, **lo que viaja a Cognito es
`users.external_id` y ya no el correo**, así que si `handle_distinto_del_correo` no da 0 hay filas
que alguien tocó a mano y hay que mirarlas primero. Dieron `0, 0, 0` el 10/09, y desde entonces
ningún código escribe `users.email` ni `users.external_id`.

**Que no cambia para los clientes.** El contrato OpenAPI de esta release es **byte-idéntico** al de
`1.30.0` —generado con `app.openapi()` en las dos ramas y comparado—, y los códigos y textos de
error son los mismos. Importa porque los clientes ramifican sobre ellos: `nexus-web` clasifica por
status y filtra el detalle con una allowlist, e iOS convierte `403` + detalle con «verif» en
`emailNotVerified`.

### Added

- **Interfaz `IdentityProvider` y modelos de la `028`** (Fase 3, rebanada B1; **sin migraciones**). `app/services/identity/` es ahora la frontera con quien verifica contraseñas, y `CognitoIdentityProvider` el único sitio del repositorio con un `boto3.client("cognito-idp")` — antes había tres (`auth.py`, `users.py`, `user_commands.py`), cada uno con su traducción de `ClientError` a `HTTPException` ligeramente distinta de las otras. Nada de Cognito cruza la interfaz: ni `AuthenticationResult`, ni `ChallengeName`, ni `ClientError`; salen `Sesion` y las excepciones de `app/services/identity/errors.py`
  - `User` declara `external_id`, `identity_provider` y `brand_account_id`, y **pierde el `unique=True` de `email`**: la unicidad la hacen los dos índices parciales de la `028`, que la vuelven por marca. `Account` declara `identity_provider` e `idp_config`. Al existir los modelos, **el comparador de deriva empieza a cubrir la `028`** — igual que pasó con la `027`
  - Los endpoints **autentican con el handle de la fila (`external_id`), no con el correo**. Hoy valen lo mismo en toda fila existente —la `028` lo rellenó desde el correo y su trigger lo mantiene—, y es lo que hace que la rebanada B2 sea un cambio de una línea
  - `_handle_por_defecto` en el modelo repite del lado de la aplicación lo que hace el trigger `users_identidad_before`: el harness de tests construye el esquema con `create_all()` y no tiene triggers, así que sin él toda alta reventaría contra el `NOT NULL`
  - **Ninguna respuesta HTTP cambia.** Es un refactor: los códigos y los detalles de `/auth/login`, `/auth/refresh`, `/auth/logout`, `/auth/password`, `/auth/reset-password`, `/auth/verify-email` y `/users/accept-invitation` son los de antes, y hay tests que lo fijan

- **`PATCH /devices/{id}/status` gana un test con un PASETO de servicio firmado de verdad**, más su contraparte negativa (un token con otro rol recibe 401). El test que llegó con `1.29.1` sustituye la dependencia por un `AuthResult` fabricado a mano, así que comprueba qué hace el endpoint con el resultado pero **nunca pasa por `decode_service_token`**: con ese override puesto, cambiar `required_role` en `deps.py` no rompía ningún test y GAC volvía a comerse un 401 en producción. Comprobado rompiendo el rol a propósito — el test nuevo falla, el viejo sigue en verde

### Changed

- **`docs/RELEASE.md` describe el modelo de ramas, que hasta ahora no mencionaba `master` ni una vez.** `develop` es la troncal; `master` es el puntero a producción y se mueve con un **fast-forward desde `develop`**, no con un PR de release. Quedan escritas las dos formas que se probaron antes y por qué dolieron: etiquetar `develop` sin tocar `master` es lo que dejó la rama por defecto 27 commits atrás de producción durante el incidente de septiembre —con CodeQL mirando solo ahí—, y un PR por release cuesta dos rondas de CI, hace chocar el corte del changelog con las ramas de trabajo y deja en `master` un commit de merge que `develop` no tiene
  - Se documenta el camino del **hotfix**: ramificar desde el tag anterior, no desde `develop`. El riesgo no son los conflictos sino arrastrar lo que ya está mergeado sin desplegar — el 9/09 la migración de identidad estuvo a un merge de salir dentro de una release cuya nota decía «migraciones: ninguna»
  - Y una advertencia sobre `nota-de-migracion.py`: **lee el árbol de trabajo, no el tag**. Generarla desde una rama con migraciones sin liberar hace que anuncie migraciones que la release no lleva. Pasó ese mismo día
- **`gac-web/docs/RELEASE.md`** gana el mismo paso de espejo y una sección de dependencias entre repos, con el caso del 9/09: `v1.7.4` exigía `siscom-admin-api v1.29.1` desplegada, y sacar la consola primero habría dado 401 en Asignación con un despliegue en verde

### Fixed

- **`POST /users/accept-invitation` no mandaba el atributo `email` al marcar el correo como verificado en Cognito**, que es justo lo que documenta el test de `verify-email` desde que se escribió («Cognito exige `email` junto a `email_verified`»). Los dos flujos comparten ahora la misma llamada del adaptador, así que el descuadre no puede volver

## [1.30.0] - 2026-09-09

**Migraciones.** `028_identidad_esquema`. Cabeza: `027_tenancy_esquema` → `028_identidad_esquema`.

**Rollback.** Revertir la imagen basta para volver atrás en el código: quitar una restricción no
rompe a la versión anterior, que sigue creando usuarios como siempre. Si además hiciera falta
revertir el esquema, **antes** de desplegar el tag viejo y desde la imagen nueva:

```bash
docker run --rm --network siscom-network --env-file .env \
  siscom-admin-api:latest alembic downgrade 027_tenancy_esquema
```

⚠️ **Ese `downgrade` puede abortar a propósito**, y es la diferencia con todas las releases
anteriores: repone `users_email_key` —la unicidad global de correo— y si para entonces dos marcas
ya comparten uno, esa unicidad ya no es cierta. La migración lo detecta y aborta con el recuento
en el mensaje en vez de dejar la base a medias. **La ventana de reversión segura no llega hasta el
release siguiente: llega hasta el primer correo duplicado entre marcas**, que no puede existir
mientras la rebanada B no salga y ningún partner tenga dominio.

### Added

- **Fase 3, rebanada A — el esquema de identidad** (`028_identidad_esquema`). Es la mitad *expand* del expand/contract: ningún modelo, endpoint ni servicio conoce todavía estas columnas, y el código que las usa sale en el release siguiente
  - `users.external_id` (`NOT NULL`) — el handle opaco ante el proveedor: el `Username` de Cognito. Correo para los usuarios que ya existen, cuyo username es inmutable; UUID para los que cree la rebanada B. **No reemplaza a `cognito_sub`**: uno es con qué se autentica, el otro es qué sujeto afirma el token, que es lo que compara `deps.py`. Ninguno se deduce del otro
  - `users.brand_account_id` (FK a `accounts`, `ON DELETE RESTRICT`) — la marca dueña de la credencial. **`NULL` no es «sin marca», es la marca por defecto**: la que se sirve a cualquier `Host` que no resuelva a un dominio verificado, y hoy son todos los usuarios. Rellenarlo con la raíz de la cuenta de cada quien sería la traducción mecánica y estaría mal — los ataría a una marca sin dominio por el que entrar, y rompería su login cuando `/auth/login` empiece a filtrar por marca
  - `users.identity_provider`, `accounts.identity_provider` y `accounts.idp_config`, con `CHECK` sobre la lista de proveedores que el código sabe manejar. El enrutamiento va **por cuenta y no por variable de entorno**: si fuera global, mover a un partner enterprise a WorkOS obligaría a mover a todos (§5, regla 2). `idp_config` lleva configuración, nunca credenciales
  - **Se quita `users_email_key`, la unicidad global de correo.** Es el único cambio no aditivo de la migración y el punto entero de la fase: dos personas distintas, una en cada marca, con el mismo correo. Que Cognito lo permite está verificado contra el pool productivo por ejecución, no deducido — la premisa contraria, sostenida un mes, era sobre lo que hace la aplicación y no sobre lo que impone el proveedor
  - En su lugar, **dos índices únicos parciales** que se reparten la tabla: `(brand_account_id, email)` donde la marca está puesta y `(email)` donde es `NULL`. Uno solo dejaría a todo el padrón actual sin unicidad de correo, en silencio, porque en Postgres dos `NULL` nunca chocan. Se crean **antes** de quitar la restricción, así que no hay ni un instante sin cobertura. `NULLS NOT DISTINCT` haría lo mismo en un objeto, pero exige Postgres 15+ y la versión de producción no está verificada desde el repositorio
  - **Un trigger sostiene la ventana entre los dos releases**: rellena `external_id` con el correo cuando el alta viene sin él, que es exactamente lo que el código viejo acaba de hacer contra Cognito. No pisa un valor explícito —la rebanada B escribe UUID y gana— y no sigue los cambios de correo, porque el username de Cognito es inmutable. Se borra en la migración *contract*
  - [ADR-007](docs/architecture/adr/007-identidad-por-marca-y-handle-opaco.md) y `docs/runbooks/desplegar-identidad.md`. El runbook trae la comprobación contra el pool —que el username de todo usuario existente sea su correo—, **corrida el 9/09: 24 de 24 personas coinciden exacto**. El único descuadre es una cuenta de servicio interna sin correo, aceptada a sabiendas. No bloquea el despliegue: quien pueda entrar hoy tiene username == correo, porque el login pasa el correo como username y el pool no lo tiene como *alias attribute*. Sí hay que tenerla cerrada **antes de la rebanada B**, que es cuando el handle empieza a usarse
  - `tests/test_identidad_esquema.py` (24 pruebas) sobre la base desechable con el esquema productivo, y no sobre `create_all()`: el harness normal seguiría creando la unicidad global de correo que esta migración quita, así que un test escrito ahí probaría lo contrario de lo que hay en producción
  - **La reversión puede ser imposible, a propósito.** El `downgrade` repone `users_email_key`, y si para entonces dos marcas ya comparten un correo, aborta con el recuento en el mensaje en vez de dejar la base a medias. La ventana de reversión segura no llega hasta el release siguiente: llega hasta el primer correo duplicado

## [1.29.1] - 2026-09-09

**Migraciones.** Ninguna. La cabeza sigue en `027_tenancy_esquema`, que entró con `1.28.0`.

**Rollback.** Redesplegar el tag anterior: no toca el esquema, así que no hay nada que revertir
en la base ni orden que respetar.

### Fixed

- `PATCH /devices/{id}/status` acepta el token PASETO de GAC (`service=gac`, `role=GAC_ADMIN`), no solo Cognito. GAC no tiene usuario Cognito en este servicio: sin este cambio, mover un dispositivo por la puerta que valida transiciones, escribe `unit_devices` y publica Kafka devolvía 401. `performed_by` queda nulo cuando autentica el servicio, y el evento anota el rol.


## [1.29.0] - 2026-09-08

**Migraciones.** Ninguna. La cabeza sigue en `027_tenancy_esquema`, que entró con `1.28.0`.

**Rollback.** Redesplegar el tag anterior: no toca el esquema, así que no hay nada que revertir
en la base ni orden que respetar.

### Added

- **Fase 2, rebanada B — el código de tenancy.** Modelos SQLModel encima de lo que creó la migración `027`, resolución de capabilities comerciales con techo descendente, y `GET /tenant-config`. **No trae migraciones**: es la mitad *contract* del expand/contract, código que empieza a usar columnas que llevan días en producción
  - `app/models/tenancy.py` (`TenantDomain`, `TenantBranding`), `AccountCapability` en `capability.py` junto a sus hermanas, y `Account` gana `parent_account_id`, `account_type` y `account_path`
  - **Al existir los modelos, el comparador de deriva empieza por fin a cubrir la `027`.** Verificado: 63 tablas revisadas, sin deriva
  - **`account_path` lo siguen manteniendo los triggers.** El modelo lo declara para poder leerlo, pero escribirlo desde la aplicación no tiene efecto: el trigger `BEFORE` lo recalcula desde el camino del padre. Está dicho en el módulo y en los tests, porque el harness normal construye el esquema con `create_all()` y ahí **no hay triggers** — de esos tests no se puede concluir que escribirlo a mano funcione

- **`app/services/account_capabilities.py` — el techo descendente.** Camina el `account_path` de la raíz a la hoja: `min` para enteros, `AND` para booleanos. Mero Mero no puede darle a Empresa 500 más de lo que Geminis le dio a Mero Mero, y eso es lo que hace delegable la reventa (§4)
  - **Sin fila no significa cero, significa que no restringe.** Es §17 —«vacío no es sin límite»— en el sitio donde más daño haría: si «sin fila» fuera cero, el sistema denegaría todo hasta configurar cada cuenta una por una; si fuera «sin límite», un descendiente sin fila escaparía del techo de su ancestro
  - **El valor por defecto no entra en el plegado**, solo se usa cuando no hay ninguna fila en todo el camino. Si entrara, conceder 5 000 subcuentas daría `min(default, 5000)` = 0 y el permiso otorgado no serviría de nada
  - `limitado_por` dice **qué cuenta impone el techo**, comparando el valor propio contra el efectivo en vez del orden en que se plegaron: con `A(5) → B(10) → C(3)` quien manda es C, y atribuir el recorte al de A sobre B sería una explicación falsa
  - En `text` no hay techo —un texto no tiene orden— y gana el más cercano a la hoja. Queda documentado con un test para que, cuando se definan los modos de `self_signup_mode`, la decisión sea consciente
  - `validar_limite` trata el **0 como cero**, al revés que el servicio de organización, donde `<= 0` es «ilimitado». Es deliberado: los defaults de aquí valen 0 para que una cuenta sin permiso explícito no pueda revender ni reclamar dominios

- **`GET /tenant-config`** — qué marca corresponde al `Host` de la petición. Público y sin autenticación por diseño: lo consume el `hooks.server.js` de nexus-web-page antes de que exista sesión, para que el primer HTML salga ya con la marca correcta y no con la de Geminis durante 200–800 ms — que es además lo que arruina el unfurl de WhatsApp, donde el crawler no ejecuta JavaScript
  - **El Host resuelve apariencia y nunca autoriza.** Por ahí no sale un solo dato de cliente, **ni siquiera el `account_id`** de la marca: el endpoint es enumerable por diseño y ese id es el que después aparece en el predicado de aislamiento. Hay un test que lo fija
  - Solo sirve dominios `VERIFIED`. Uno en `PENDING` lo puede reclamar cualquiera hasta que demuestre control por DNS, y servir su marca antes permitiría suplantar a un partner apuntando un CNAME
  - Un Host desconocido responde **200 con la marca genérica**, no 404: el fallo más probable —un dominio recién dado de alta— dejaría si no la aplicación sin pintar en vez de pintarla neutra
  - `Vary: Host` además de `Cache-Control`. Sin él una caché intermedia serviría la marca de un partner a otro

### Fixed

- **`OrganizationCapability.is_expired()` lanzaba `TypeError` con cualquier override que tuviera fecha de caducidad.** `expires_at` es `TIMESTAMP WITH TIME ZONE` —la columna la añadió la migración `026`— y `utcnow()` devuelve naive a propósito, así que compararlas sin normalizar da `can't compare offset-naive and offset-aware datetimes`. Está en el **camino central de resolución de capabilities**: la petición entera reventaba. Se salvaba solo porque la columna es del 7/09 y todavía no hay filas que la usen
  - Es **el mismo fallo que tenía `Subscription.is_active()`**, y se arregla igual, con `as_naive_utc()` en la frontera de comparación
  - **Por qué los tests no lo veían**: `test_organization_capability_is_expired` construye la fecha en Python, donde sale naive, así que pasaba en verde mientras el código reventaba con un valor real leído de Postgres. Es la lección de §20 en pequeño — un test que no puede fallar por la razón por la que falla producción no informa de nada. Se añade el caso *aware*
  - Lo encontró un test de la rebanada B al copiar ese mismo `is_expired()` para `AccountCapability`


- **CodeQL pasa a advanced setup y cubre `develop`** (`.github/workflows/codeql.yml`). El default setup analiza únicamente la rama por defecto y los PRs que la apuntan, y en este repositorio el trabajo real pasa por `develop` — los tags `v1.27.0` y `v1.27.1` se cortaron directamente sobre esa rama, así que fue código desplegado a producción sin que CodeQL lo hubiera mirado nunca. El workflow reproduce la configuración que ya había (lenguajes `actions` y `python`, suite `default`, threat model `remote`, corrida semanal); lo único que cambia es que ahora corre en las mismas ramas que `ci.yml`
  - El caso que lo destapó: la fuga de `/health` entró en `1.27.0` el 5/09 y se marcó el 7/09, al abrir el primer PR contra `master` desde entonces. Esos dos días son el hueco
  - Los demás escáneres —Gitleaks, Semgrep, pip-audit y OSV— **ya cubrían las dos ramas** vía `ci.yml`. Lo que faltaba en `develop` era el análisis de flujo de datos de CodeQL, que es justo el que encontró la fuga: Semgrep no la marcó
  - **Requiere desactivar el default setup antes de mergear**, porque los dos modos no conviven: con el default activo, este workflow falla

### Security

- **Registro de riesgos aceptados en `docs/security/threat-model.md`.** La excepción de `ecdsa` (`GHSA-wj6h-64fc-37mp` / `CVE-2024-23342` / `PYSEC-2026-1325` — Minerva, sin versión corregida) estaba repartida entre `osv-scanner.toml` y `scripts/pip-audit-scan.sh`, y Dependabot no la conocía: la misma decisión, tomada dos veces, seguía apareciendo como alerta alta sin atender. Ahora hay un solo registro con el razonamiento, los tres sitios donde vive la excepción y **la condición que la invalidaría** — que se firme con ECDSA o se acepte ES256 en `jwt.decode`
  - No aplica a este servicio: Minerva ataca el *firmado* ECDSA sobre P-256, y `app/core/security.py` hace una sola llamada, `jwt.decode(..., algorithms=["RS256"])`. RS256 es RSA
  - Lo que cerraría el asunto de raíz es quitar `python-jose` —`PyJWT` + `cryptography` verifica RS256 sin arrastrar `ecdsa`—, pero toca el camino de verificación de tokens y merece su propio PR

## [1.28.0] - 2026-09-07

**Migraciones.** Trae una: `027_tenancy_esquema`. Cabeza `026_reconciliacion` → `027_tenancy_esquema`.

**Rollback.** Revertir la imagen basta: la migración es aditiva (expand/contract), así que el código
anterior convive con el esquema nuevo e ignora lo que no conoce. Para revertir también el esquema hay
que hacerlo **antes** de desplegar el tag viejo, porque el archivo de la migración vive en la imagen
nueva: `alembic downgrade 026_reconciliacion`. Sin ese paso, desplegar un tag anterior falla con
`Can't locate revision identified by '027_tenancy_esquema'`. El downgrade **borra** lo que la 027
creó —es seguro poco después de liberar y deja de serlo en cuanto entre dato nuevo— y no revierte las
definiciones de capability ya referenciadas (ver `docs/runbooks/desplegar-tenancy.md`).

### Added

- **Esquema de tenancy — Fase 2, rebanada A** (migración `027_tenancy_esquema`). Árbol de cuentas con `parent_account_id` y `account_path` (`uuid[]` + índice GIN), `accounts.account_type` (`PLATFORM`/`RESELLER`/`CUSTOMER`), y las tablas `account_capabilities`, `tenant_domains` y `tenant_branding`. Aditiva pura: **ningún modelo, endpoint ni servicio la conoce todavía**, así que puede desplegarse sin que cambie nada visible, o quedarse mergeada sin desplegar. Es la mitad *expand* del expand/contract; la rebanada B —modelos, resolución de capabilities con techo descendente y `GET /tenant-config`— va en el release siguiente
  - **Sin prerrequisitos de despliegue**: `alembic upgrade head` y ya. Ni extensiones, ni privilegios que `siscom_migrator` no tenga, ni un paso manual previo por parte de nadie
  - **`account_path` lo mantienen dos triggers, no la aplicación.** Ese camino es el predicado de aislamiento entre clientes: un invariante del que depende quién ve los datos de quién no puede vivir en una capa que se salta con un `INSERT` manual o un script de soporte. El trigger `BEFORE` construye el camino desde el del padre y rechaza ciclos y profundidad > 5; el `AFTER` propaga a los descendientes cuando se mueve una rama
  - **`ck_accounts_camino_termina_en_si_misma`** ancla el invariante: `@>` casa un elemento en cualquier posición —que es lo que se quiere para pertenencia al subárbol— pero eso solo vale mientras el array sea de verdad la cadena de ancestros, y un id suelto ahí sería un falso positivo en una comprobación de autorización. La restricción no es redundante con el trigger: sobrevive a una restauración, a una carga con `session_replication_role = replica` y a un `DISABLE TRIGGER`
  - `tenant_domains.hostname` es `UNIQUE` **global**, no por cuenta: si dos marcas reclaman el mismo `Host`, quien resuelve tiene que elegir, y esa es una decisión que no debería existir. Se guarda en minúsculas por restricción, para que la búsqueda sea una igualdad indexable y no un `lower()`
  - `account_capabilities` lleva `UNIQUE (account_id, capability_id)` y un `CHECK` de un solo valor. `organization_capabilities` no tiene ninguno de los dos, y por eso admite hoy dos overrides que se contradicen
  - Las cuentas existentes quedan todas como raíz con `account_type = 'CUSTOMER'`. **Cuál es la cuenta `PLATFORM` de Geminis es una decisión de negocio y la toma la rebanada B.** `self_signup_mode` no se siembra: sus modos y sus defensas siguen sin acordarse

- **ADR-006 — el camino materializado va en `uuid[]`, no en `ltree`**, que es lo que decía §3 del documento de arquitectura. Se midió sobre un árbol con la forma del negocio real (44 041 cuentas, 480 000 unidades): en la consulta que de verdad se ejecuta —el join contra la tabla grande— las dos codificaciones **empatan** (16.4 ms contra 15.8 ms), así que el rendimiento no decide. Lo que sí mide algo es el recursivo sobre `parent_id`: 3 210 buffers contra 6, que es lo que justifica materializar el camino
  - Deciden tres cosas que no son rendimiento: `CREATE EXTENSION ltree` exige `CREATE` sobre la base y `siscom_migrator` solo tiene `CONNECT` (comprobado contra un rol acotado igual que el productivo); una etiqueta de `ltree` no admite guiones, así que el UUID entra codificado y hay que reconstruirlo en cada consulta, cada log y cada sesión de soporte; y la política RLS que §3 declara como destino necesita con `uuid[]` un solo id del actor en vez del camino entero serializado en un GUC
  - De regalo: índice de 3.4 MB en vez de 14 MB, `ARRAY(PGUUID)` nativo en SQLAlchemy en vez de un `TypeDecorator` propio, y se acabó el `SAWarning: Did not recognize type 'ltree'` del comparador de deriva

- **`tests/test_tenancy_esquema.py` — 38 pruebas sobre esquema sin modelos.** Las dos redes habituales no alcanzan a la rebanada A: el harness construye la base con `create_all()`, así que solo conoce lo que algún modelo declara; y el comparador de deriva mira en una sola dirección, así que de la `027` solo comprueba que aplique. Este módulo levanta una base desechable con el snapshot productivo más `alembic upgrade head` y ejercita los triggers con datos: caminos, ancestros, reparentado con nietos, ciclos, profundidad, y cada restricción de las tres tablas nuevas. Incluye el `downgrade` y la vuelta a subir
  - Las dos capas de defensa del camino se prueban por separado, y la primera se descubrió al escribir la segunda: con el trigger activo, escribir `account_path` a mano **no falla** —se recalcula y se ignora—, así que la restricción solo se puede ejercitar desactivando el trigger, que es exactamente el escenario para el que existe
  - `tests/esquema_desechable.py` recoge la maquinaria de la base desechable, que antes vivía dentro de `scripts/verificar-deriva.py`. El script pasa a usarla; su comportamiento no cambia

- `docs/runbooks/desplegar-tenancy.md` — qué añade la migración, las tres comprobaciones de después, y qué no revierte el rollback (las definiciones de capability ya referenciadas)

- **Comprobación de deriva entre migraciones y modelos en CI** (`scripts/verificar-deriva.py` + `tests/schema/`). Parte del snapshot del esquema **productivo**, lo stampea, corre `alembic upgrade head` y compara el resultado contra `SQLModel.metadata`. Falla el PR si algo no cuadra.
  - **No se puede hacer con `create_all()`**: comparar la metadata contra una base construida desde esa misma metadata es tautológico y siempre sale vacío. Solo dice algo cuando el esquema viene de otro sitio
  - El snapshot corresponde a `025_device_and_unit_refs`, **antes** de la `026`, para que `upgrade head` ejecute migraciones de verdad en vez de ser un no-op
  - Verificado que sabe fallar: con una columna inventada en un modelo devuelve código 1 y la nombra; sin deriva, 0
  - `tests/schema/README.md` documenta las cinco limitaciones del snapshot —viene de un export gráfico, no de `pg_dump`— y cómo refrescarlo


### Removed

- **`device_services` y todo lo que colgaba de él.** La migración `006` borra esa tabla a propósito y producción no la tiene: aquí producción tenía razón y lo que sobraba era el código. Verificado antes de borrar que **ningún cliente lo usa** — se buscaron las cuatro rutas (`v1/services`, `/services/active`, `/services/confirm-payment`, `/services/{id}/cancel`) en `nexus-web-page`, `geminis-labs-web-page`, `gac-web`, `apple/INexus` y `android`: cero coincidencias en los cinco.
  - Fuera: `endpoints/services.py` (4 rutas legacy, el propio archivo se declaraba "⚠️ NO USAR"), `models/device_service.py`, `schemas/device_service.py`, `services/billing.py` y `services/device_activation.py` (solo alcanzables desde `services.py`), y `services/subscriptions.py` completo — sus cinco funciones tenían **cero llamadores**
  - Fuera también sus tres tests y la prueba de humo de `/services/active` en `test_auth.py`
  - Limpiadas las relaciones en `models/plan.py` y `models/device.py`, los exports de ambos `__init__.py`, y el `include_router` de `api/v1/router.py`
  - **No se tocan las migraciones `006` ni `026`**: son historia
  - `mobility_devices.py` y `mobility_device_service.py` **no** se tocan: `MobilityDeviceService` es otra clase

### Changed

- **Los tests corren contra PostgreSQL real, no contra SQLite.** `tests/conftest.py` levantaba SQLite en memoria y construía el esquema con `SQLModel.metadata.create_all()` bajo un parche (`_patch_metadata`) que borraba los `server_default`, sustituía `UUID`/`ARRAY`/`INET`/`JSONB` por `Text` y aplanaba `table.schema`. La batería no podía fallar por casi ninguna de las razones por las que falla producción. Lo que el cambio destapó de inmediato:
  - **`create_all()` no es una definición completa del esquema.** Los tipos ENUM de `app/core/pg_enums.py` llevan `create_type=False` —los crea el SQL crudo de la migración `023`— así que sin ellos falla con `type "payment_gateway" does not exist`. El fixture los crea derivándolos del propio módulo para que no puedan divergir.
  - **Hay tablas fuera de `public`**: `api_platform.*`. El parche las renombraba a `api_platform_api_alerts` en `public`, así que se probaban contra una tabla que el código de producción nunca toca.
  - Los tres `if dialect != postgresql` del código de producción desaparecen. El más relevante: `app/db/locks.py` hacía `return` temprano, de modo que **el lock consultivo que impide el doble cobro era un no-op declarado bajo test** y tenía cobertura cero.
  - Aislamiento por test: transacción externa revertida al terminar, con `join_transaction_mode="create_savepoint"` para que los `commit()` de fixtures y código se traduzcan a SAVEPOINTs. Antes se hacían `create_all` + `drop_all` de 73 tablas **por cada test**.
  - Los seis tests que fallaron al cambiar de motor: tres eran el bug de `is_active()` de arriba; dos insertaban un `Command` sin que existiera su `Device` —SQLite no aplica claves foráneas, y sin `relationship` declarada SQLAlchemy no ordena los `INSERT`—; uno afirmaba un orden de claves que JSONB no preserva (las normaliza por longitud y bytes). Ninguno de los tres últimos es bug de producción, pero los tres fijaban suposiciones falsas
  - `ci.yml` levanta un servicio `postgres:15`; el harness local es `docker-compose.db.yml`. Se eliminan `tests/sqlite_dialect.py` y `tests/test_sqlite_dialect.py`.

### Security

- **`/health` deja de devolver el error de conexión de la base en el cuerpo.** `check_database()` devuelve `str(exc)` de SQLAlchemy, y un `OperationalError` real trae el host, la IP, el puerto y el usuario de la conexión —`connection to server at "siscom-db" (172.18.0.4), port 5432 failed: FATAL: password authentication failed for user "siscom"`—. `/health` no exige autenticación y el origen del ALB sigue abierto, así que una base caída se convertía en un mapa de la infraestructura para quien sondeara el endpoint. Ahora el cuerpo dice `"database unreachable"` y el error real queda en el log de `check_database()`, que es donde hace falta para diagnosticar. Detectado por CodeQL (`py/stack-trace-exposure`) en el PR #64
  - **No es una regresión de esta versión**: entró con `/health` en `1.27.0` y lleva desplegado desde el 5/09. La alerta aparece ahora porque el diff contra `master` lo incluye por primera vez
  - El despliegue no se entera: `deploy.yml` solo comprueba `"database": "ok"`, nunca el detalle
  - El test de la base caída pasa a afirmar lo contrario de lo que afirmaba: en vez de exigir que el detalle sea el error, exige que host, IP, puerto y driver **no** aparezcan en la respuesta

## [1.27.1] - 2026-09-07

### Fixed

- **El `set -eo pipefail` del despliegue rompía las comprobaciones que endurecía.** `docker ps | grep -q NOMBRE`: `grep -q` sale al primer match, el productor recibe `SIGPIPE` y termina con 141, y `pipefail` da el pipeline por fallido **aunque `grep` haya encontrado lo que buscaba**. En el despliegue de `v1.27.0` el contenedor levantó bien (`Up 5 seconds`) y el script lo dio por caído, revirtiendo la imagen sin necesidad. Nueve comprobaciones tenían esa forma; ahora usan `docker ps -q --filter "name=^X$"` y here-strings (`<<<`) en vez de pipes, y están probadas contra contenedores reales con `pipefail` activo, no solo con `bash -n`

## [1.27.0] - 2026-09-06

Reconciliación del esquema de producción con la cadena de migraciones, y el mecanismo que mantuvo esa divergencia invisible.

### Added

- Deuda de migraciones — diagnóstico, harness y protecciones (no incluye la reconciliación en sí):
  - `docker-compose.db.yml` + `scripts/db-local.sh`: Postgres local con la misma imagen que producción (`timescale/timescaledb:2.15.1-pg15`) para probar migraciones y DDL antes de tocar producción. Incluye `restore` de un dump productivo y `anonymize`. Es prerrequisito de la Fase 2: `ltree` y los índices GIST de `account_path` no se pueden probar en SQLite, que es contra lo que corren hoy los tests
  - `scripts/alembic-probe.py`: sonda **de solo lectura** que, para cada revisión, comprueba si su efecto ya está presente en el esquema vivo, y dice si el historial es reconciliable con un solo `alembic stamp` o necesita una migración de línea base. Es el paso que falta correr contra producción
  - `tests/test_migrations_chain.py`: integridad de la cadena en cada PR — cabeza única, base única, sin huérfanos ni ciclos, todas las revisiones alcanzables desde la cabeza, `downgrade()` con cuerpo real, y prefijo de fichero coherente con el orden de la cadena. Antes nada en CI miraba las migraciones
  - `DB_MIGRATION_USER` / `DB_MIGRATION_PASSWORD`: credencial de migraciones separada de la de runtime, que solo tiene DML. Alembic la usa cuando existe y cae a `DB_USER` cuando no, así que no rompe el despliegue actual
  - `docs/runbooks/reconciliar-historial-alembic.md`: el diagnóstico medido y el procedimiento

### Fixed

- **Reconciliación del esquema (migración `026`).** Medida contra el DDL de producción del 5-6 de septiembre, no deducida. La sonda dio 21 de 25 revisiones presentes con huecos en `004`, `021`, `022` y `024`: no monótono, así que ningún `alembic stamp` único deja el historial correcto. Repara, con endpoints vivos afectados:
  - `api_idempotency_requests` (mig. `021`) — `POST /payment-intent` inserta ahí la reserva de idempotencia antes de llamar a Stripe. Sin la tabla, el endpoint de cobro falla
  - `account_tax_profiles` (mig. `024`) — timbrado CFDI
  - `plan_products` — la usa `internal/plans.py` con un `JOIN`; no la crea ninguna migración, estaba solo en `initdb/02_schema.sql`
  - Siete columnas: `subscriptions.grace_until` y `renewal_last_error`, `invitations.role`, `organization_capabilities.reason` y `expires_at`, `order_items.created_at`, `trip_events.value`
  - `gateway_event_status += 'processing'`
  - **Es idempotente objeto por objeto, no por migración**: la `022` está *parcialmente* aplicada (tiene `dunning_last_attempt` y `dunning_next_attempt`, le faltan las otras dos), así que reejecutarla entera fallaría
  - No toca `device_services` —la mig. `006` la borra a propósito y el sobrante es el modelo— ni `unified_sim_profiles`, que sí existe en producción
  - Ensayada contra una réplica del esquema productivo: aplica, revierte, reaplica, y es no-op sobre un esquema ya reparado
- `docs/RELEASE.md` decía que revertir una liberación era redesplegar el tag anterior. **Eso falla cuando la liberación trae una migración**: alembic aborta con `Can't locate revision identified by ...` porque esa revisión no existe en la historia del código viejo. Ahora documenta los dos pasos reales, en orden, y aclara que el primero —revertir la imagen— basta casi siempre, porque las migraciones son aditivas por política (expand/contract)
- `scripts/nota-de-migracion.py`: genera la nota de migración y rollback de una liberación —qué revisiones añade y el `downgrade` exacto— derivándola del repositorio, para que no pueda envejecer. La plantilla de PR la pide como obligatoria, aunque sea para decir que no hay migraciones
- `scripts/alembic-probe.py` buscaba en `public` tablas que las migraciones `016`–`019` crean en los esquemas `team` y `mobility`, así que daba cuatro revisiones por ausentes cuando sí estaban aplicadas. El veredicto real es 21/25, no 17/25

### Changed

- `deploy.yml` propaga `DB_MIGRATION_USER` (variable) y `DB_MIGRATION_PASSWORD` (secret) en los tres sitios que hacen falta: el bloque `env:`, la lista `envs:` del `ssh-action` —el que se olvida— y el heredoc del `.env`. Anuncia en el log con qué usuario va a migrar, y aborta si el usuario está definido pero la contraseña sale vacía, que es el síntoma de haberla guardado como variable en vez de como secret
- `/health` consulta la base de datos y expone `schema_revision` (la revisión de alembic aplicada, o `null` si `alembic_version` no existe). Devuelve **503** cuando la base no responde. Antes era un diccionario estático: el healthcheck de Docker y el bucle de espera del despliegue daban verde con la base inservible
- `deploy.yml` — `set -eo pipefail` en los dos scripts remotos: sin él, un paso que fallaba no abortaba el despliegue, que terminaba imprimiendo "completado exitosamente". Además:
  - las migraciones corren **antes** de tocar el contenedor en marcha y abortan el despliegue si fallan, dejando el servicio anterior sirviendo intacto
  - la imagen anterior se etiqueta `:rollback` y se restaura si el contenedor nuevo no levanta o no llega a *healthy*
  - se registra la revisión de esquema antes y después de migrar
  - la verificación del endpoint `/health` deja de ser un *warning* y aborta el despliegue

## [1.26.0] - 2026-09-04

### Added

- Control plane de notificaciones: la API publica a Kafka **después del commit** cuando cambia una asignación unidad-dispositivo, un grant `user_units` o un token push. Tópicos nuevos: `KAFKA_UNIT_DEVICES_UPDATES_TOPIC` (`unit-devices-updates`) y `KAFKA_USER_UNITS_UPDATES_TOPIC` (`user-units-updates`). Cubre `POST/DELETE` de `/user-units`, `/units/{id}/users`, `/units/{id}/device`, `/unit-devices`, `PATCH /devices/{imei}/status` (asignado/devuelto) y register/deactivate de `/user-devices`

## [1.25.0] - 2026-09-03

### Added

- Fase 1 — aislamiento del plano de datos:
  - `devices.device_ref` y `units.unit_ref`: identificadores opacos (UUIDv4) para direccionar dispositivos y unidades sin exponer el IMEI. `device_id` **es** el IMEI (lo renombró la migración 005), así que hoy acaba en los logs de acceso de uvicorn y del ALB y en cabeceras `Referer`. Las columnas se añaden; `device_id` y `units.id` siguen existiendo y funcionando (migración `025`)
  - `app/utils/data_token.py`: emisión de data tokens PASETO **v4.public** (Ed25519). admin-api firma, siscom-api solo verifica — asimétrico a propósito: con v4.local el verificador también podría firmar
  - `app/services/scope_store.py`: el alcance se materializa en Valkey (`dt:scope:<ref>`), con TTL por encima del token. Las claves del índice de revocación por propietario se derivan por HMAC, de modo que Valkey nunca revela de quién es un alcance
  - `POST /auth/data-token` y data token adjunto al login. El plano de datos no puede impedir iniciar sesión: sin Valkey el login sigue funcionando y el cliente reintenta contra ese endpoint
  - Autorización temporal: el alcance lleva ventanas `[from, to)`; una petición parcialmente cubierta se recorta al rango autorizado en vez de rechazarse, y `to: null` significa ventana abierta (datos en vivo autorizados)
  - Revocación: `DELETE /units/{id}/share-location` invalida los enlaces emitidos con el formato nuevo
  - ADR-005 documenta el diseño y la secuencia de despliegue

## [1.24.0] - 2026-08-25

### Added

- Cotización en servidor para los cobros de Stripe: el importe deja de venir del cliente y se calcula en el backend (PR #45)
- Idempotencia de peticiones (`app/services/idempotency_service.py`, migración `021_api_idempotency`) para que un reintento de cobro no genere un segundo cargo (PR #45)
- Servicio de renovaciones de suscripción (`app/services/renewal_service.py`, migración `022_subscription_renewal`) (PR #45)
- Comprobante interno en PDF (`app/services/receipt_pdf.py`, `app/services/invoice_numbering.py`) (PR #45)
- Perfiles fiscales por cuenta (migración `024_account_tax_profiles`) y CFDI emitido **a petición**, no en cada cobro (PR #45)
- `app/services/money.py` y `app/db/locks.py`; esquema de métodos de pago reestructurado (migración `023_payment_methods_schema`) (PR #45)
- Guía `docs/guides/pagos-flujo-completo.md` (PR #45)

### Changed

- Stripe y Facturapi pasan a ser **opcionales**: sin claves en el ambiente el servicio arranca igual y esas integraciones quedan inactivas (PR #45)

## [1.23.1] - 2026-08-08

### Fixed

- `ALLOWED_ORIGINS` en formato CSV ya no rompe el arranque. El campo estaba declarado como `list[str]`, así que `EnvSettingsSource` corría `json.loads` sobre el valor crudo antes de que se ejecutara el validador `parse_allowed_origins`: cualquier CSV —o una cadena vacía— reventaba con `SettingsError` y tiraba el contenedor. Ahora se anota como `Annotated[list[str], NoDecode]` y el validador existente recibe el string sin tocar (PR #38)
- Guía de deploy: las variables de GitHub viven en el environment `test`, no a nivel repositorio. Una variable creada en el scope equivocado se ignora en silencio, porque las de environment tienen precedencia (PR #38)

### Added

- `tests/test_config.py`: cobertura del parseo de `ALLOWED_ORIGINS` desde variables de entorno — CSV, JSON array, espacios, slash final, duplicados, valores en blanco, JSON malformado y el default (PR #38)
- Troubleshooting del `SettingsError` de `ALLOWED_ORIGINS` y del scope de variables en `docs/guides/github-actions-deployment.md` (PR #38)

### Changed

- `pydantic-settings` 2.1.0 → 2.15.0. `NoDecode` se agregó en 2.3.0; el pin previo era de diciembre 2023, 14 minors atrás de `pydantic==2.12.5` (PR #38)

## [1.23.2] - 2026-08-09

### Fixed

- `KAFKA_TEAM_RULES_TOPIC` ya llega al contenedor. La variable estaba declarada en `app/core/config.py` y `TeamRulesKafkaProducer` la leía vía `settings`, pero no se propagaba en ningún compose ni en `deploy.yml`: el topic de teams era en la práctica un hardcode y no se podía cambiar sin reconstruir la imagen, a diferencia de los otros cuatro topics de Kafka. Se añade a `.env.example`, ambos compose y a las tres apariciones de `deploy.yml` —bloque `env`, lista `envs:` del `ssh-action` y el heredoc que escribe el `.env` remoto— (PR #40)

## [1.23.3] - 2026-08-10

### Fixed

- `POST /auth/verify-email` ya no devuelve 500 cuando el usuario ya existe en Cognito. Esa rama llamaba a `admin_update_user_attributes` solo con `email_verified`, y Cognito exige que `email` viaje en la misma llamada: la excepción `InvalidParameterException` dejaba el correo sin verificar. Se incluye `email` junto a `email_verified` (PR #42)
