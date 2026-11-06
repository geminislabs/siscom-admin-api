# ADR-005: Data token del plano de datos (PASETO v4.public + Valkey)

**Estado:** Propuesto
**Fecha:** 2026-08-21
**Autores:** Equipo de Desarrollo
**Revisores:** -

## Contexto

siscom-api expone el histórico GPS y el WebSocket de posiciones sin autenticación
ni acotación por cliente, y nexus-web los consume directamente desde el navegador.
Para salir a producción como plataforma multi-marca hace falta que cada petición
al plano de datos vaya autorizada y acotada.

El requisito duro es que **siscom-api nunca sepa nada de clientes**: ni
organizaciones, ni cuentas, ni usuarios. Eso descarta reutilizar el token de
sesión de Cognito, que lleva `sub` —el `cognito_sub` con el que se identifica al
usuario en `users`— y además no dice nada sobre qué dispositivos puede leer, con
lo que siscom-api tendría que consultar el modelo de clientes para averiguarlo.

Ver [ADR-004](./004-separacion-claves-paseto.md) para el incidente que hizo
explícito por qué el verificador no debe poder firmar.

## Decisión

**PASETO v4.public (Ed25519)** con el alcance resuelto en **Valkey**.

### Token

Carga útil exhaustiva: `{jti, scope_ref, aud, iat, nbf, exp}`. Sin `user_id`, sin
`organization_id`, sin email, sin lista de dispositivos. La propiedad no es que
se respete una convención, es que **no hay dónde meter la identidad**: un
observador del token, o siscom-api entera, no puede aprender nada de ningún
cliente. En v4.public la carga va firmada pero **en claro**, así que esto es
condición necesaria, no defensa en profundidad.

`kid` en el footer desde la primera versión, aunque todavía no se rote: el footer
va en claro y autenticado, y sin él la primera rotación es un corte de servicio.

Asimetría: admin-api firma con la privada, siscom-api solo verifica con la
pública. El verificador no puede emitir credenciales.

### Alcance

    dt:scope:<scope_ref>:dev   → HASH device_ref → device_id
    dt:scope:<scope_ref>:unit  → HASH unit_ref    → unit_id

Lectura por `HGET`, que en una sola operación resuelve **autorización y
traducción**: el campo ausente (`nil`) deniega, y el valor es el identificador
con el que siscom-api consulta sus propias tablas. Así el plano de datos no
necesita migrar su esquema para dejar de indexar por IMEI ni llamar a admin-api
en el camino caliente.

La ausencia **es** la revocación, de modo que revocar es un `DEL` y no existe una
segunda lista de tokens revocados que pueda divergir de la primera.

Las **claves** del hash son opacas ([migración
021](../../../app/db/migrations/versions/021_device_and_unit_refs.py)): `device_id`
es el IMEI, y como en v4.public la carga va en claro y el token viaja en query
strings, un IMEI ahí acabaría en los logs de acceso. Que el IMEI aparezca como
**valor** no contradice eso: siscom-api ya tiene todos los IMEIs, sus tablas
están indexadas por ellos. El ref existe para que el IMEI no llegue al navegador
ni a las URLs, no para ocultárselo al plano de datos. Lo que siscom-api sigue sin
poder saber es de quién es cada flota, que es el requisito de verdad.

Una petición con varias refs de las que alguna no está autorizada se rechaza
**entera**, no filtrada al subconjunto permitido: devolver el subconjunto
convertiría la API en un oráculo de pertenencia. El cliente lo absorbe
refrescando el data token y reintentando una vez, con lo que una ref obsoleta se
cura sola.

### Autorización temporal

La pregunta no es «¿puede ver el dispositivo X?» —un booleano derivado del estado
actual, y por eso incapaz de decir nada del pasado: o lo incluye para siempre o lo
excluye para siempre, y las dos son incorrectas— sino **«¿puede ver el dispositivo
X entre t1 y t2?»**. El historial de `unit_devices` ya contenía la respuesta; se
descartaba al filtrar por asignación activa.

El valor del hash lleva la ventana:

```json
{"id":"864537040123456","windows":[{"from":"2026-01-01T00:00:00+00:00","to":"2026-03-01T00:00:00+00:00"},{"from":"2026-06-01T00:00:00+00:00","to":null}]}
```

Intervalos semiabiertos `[from, to)`, disjuntos y ordenados —los solapados se
fusionan en origen, así que el lector no normaliza—. `to: null` es **ventana
abierta** y es lo único que autoriza los datos en vivo: posición actual y
WebSocket no son una regla aparte, son el mismo predicado evaluado ahora.

Cuatro consecuencias:

1. **Se recorta, no se rechaza.** Pedir enero–diciembre habiendo tenido el equipo
   hasta marzo devuelve enero–marzo. Distinto del rechazo total sobre una
   referencia ajena: aquí no hay oráculo de pertenencia que proteger, porque quien
   pregunta ya conoce los límites de su propia ventana.
2. **Son varios intervalos, no uno.** Un equipo puede irse a otra flota y volver, y
   un modelo de intervalo único falla justo en ese caso.
3. **Un rango entero fuera de ventana es 404, no una serie vacía.** Devolver vacío
   confundiría «no tienes permiso» con «no hay datos».
4. **Lista de ventanas vacía concede cero acceso.** Un `[]` y un
   `[{"from":null,"to":null}]` son estructuralmente distintos: el segundo es un
   objeto explícito con dos nulos, nunca una lista ausente. Sin esa distinción, un
   error de codificación aquí se convertiría en acceso ilimitado en el verificador
   —y el idioma `windows or <por defecto>` lo haría solo, porque la lista vacía es
   *falsy*. Hay tests que lo fijan.

Se eliminó el camino booleano anterior (`accessible_device_ids`,
`validate_batch_device_access`) en vez de dejarlo junto al nuevo: encapsulaba la
semántica que esto sustituye, y dejarlo disponible es invitar a que alguien lo
llame.

**Límite del esquema**: `unit_devices` tiene `UNIQUE(unit_id, device_id)`
(migración 007), así que un dispositivo no puede reasignarse **a la misma unidad**
dos veces. El caso del equipo que vuelve solo produce dos ventanas si vuelve a una
unidad distinta; volver a la misma no es representable sin levantar la
restricción. El modelo admite varios intervalos; es el esquema el que hoy no puede
alimentarlos en ese caso.

**Límite conocido**: la ventana sale de la relación unidad↔dispositivo, que es de
la organización. La relación usuario↔unidad no tiene historial —`user_units`
guarda `granted_at` pero el revocado es un borrado físico—, así que un usuario al
que se le concede una unidad hoy ve el histórico del dispositivo en esa unidad
desde antes de tener acceso. Cierra la fuga entre organizaciones, no acota dentro
de una.

### Vigencia adaptativa

`exp = min(ahora + DATA_TOKEN_MAX_TTL_SECONDS, siguiente límite del alcance)`,
con un suelo de `DATA_TOKEN_MIN_TTL_SECONDS`.

Las reglas de visibilidad de team (`team.visibility_rules.schedule`) tienen
ventanas horarias: la respuesta del resolver deja de ser cierta a una hora
conocida. Emitir hasta ese instante hace exactos tanto el cierre como la apertura
de una ventana, sin imponer TTLs cortos a todo el mundo. El gancho
(`next_scope_boundary`) está cableado y hoy devuelve `None`, porque ningún cliente
consume teams todavía.

### Revocación y rastro forense

Índice inverso `dt:owner:<hmac(subject_id)>` → SET de `scope_ref` vivos. Sin él,
"revocación = `DEL`" no tendría a qué apuntar.

La clave se deriva por HMAC y no lleva el identificador en claro. Valkey es
compartido con siscom-api; si la ACL que lo restringe a `dt:scope:*` se despliega
mal, con la clave en claro siscom-api aprendería identidades de usuario. Con HMAC
no aprende nada aunque la lea: es la medida que sobrevive a un error de
configuración, y por eso no es opcional.

**Emitir revoca lo anterior del mismo sujeto.** No es un efecto colateral: si a
alguien se le estrecha el alcance, el token ancho tiene que morir en esa misma
operación y no diez minutos después.

> **Enmienda (06/11/2026, D1 del plan de data token y versiones):** emitir ya
> **no** revoca. Dos clientes del mismo usuario —la web y el móvil, o dos
> refresh que se cruzan— se mataban entre sí. El objetivo de arriba se mantiene
> por otro camino: `app/services/session_revocation.py` revoca desde el ORM, al
> confirmar, a todo sujeto cuyo alcance se estrecha (usuario desactivado,
> membresía perdida o degradada de `owner`, unidad retirada, dispositivo
> desasignado, unidad borrada o movida), venga del endpoint que venga. La
> auditoría que lo motivó encontró que sólo cuatro de catorce caminos lo
> hacían a mano. Y `deps._exigir_usuario_activo` impide que un usuario
> desactivado saque un token nuevo con su access token todavía vigente.

`dt:jti:<jti>` → clave de dueño (la HMAC, no el usuario) deja un rastro con el
mismo TTL que el alcance. siscom-api registra el `jti` en sus logs sin saber de
quién es; el cruce reconstruye a quién pertenecía un acceso, y ninguno de los dos
lados por separado identifica a nadie. El `jti` se genera antes de firmar y de
escribir, para que el rastro y el token lleven el mismo identificador.

La auditoría permanente (`AuditService.log_event`) se reserva para las sesiones
de soporte: un registro por cada refresco de diez minutos de cada usuario sería
ruido sin valor forense. El rastro en Valkey cubre la ventana corta, que es en la
que la forense sirve para reaccionar en vez de para arqueología. Los rastros
`dt:jti` no se borran al revocar —conservarlos permite investigar el uso de un
token después de revocarlo, que es justo cuando interesa.

### Propósito de la credencial

El índice inverso se separa por propósito: `dt:owner:<propósito>:<hmac>`. Sin esa
separación, renovar el data token de una sesión —que revoca lo anterior del mismo
dueño— apagaría de paso todos los enlaces de ubicación que esa persona tuviera
compartidos. Cambiar los permisos de alguien debe revocar su sesión, no lo que
compartió deliberadamente.

Los enlaces compartidos se indexan por la **unidad**, no por quien los generó, de
modo que "dejar de compartir esta unidad" apaga sus enlaces sin tocar los de otra
unidad de la misma persona. Esa es la acción que existe en el producto.

### Compartir ubicación

`POST /units/{id}/share-location` emite un data token con alcance de un solo
dispositivo y TTL propio (`SHARE_TOKEN_TTL_SECONDS`, por defecto 30 minutos: el
destinatario es una persona que abre un enlace, no un cliente que sabe refrescar).
Eso le da al producto algo que no tenía —`DELETE /units/{id}/share-location`—:
con el formato v4.local anterior, un enlace emitido era válido sus treinta
minutos y no había forma de apagarlo.

La migración va detrás de un interruptor explícito
(`SHARE_LOCATION_USE_DATA_TOKEN`, por defecto `false`) y no de la detección de si
hay claves configuradas. El cambio de formato tiene que ocurrir **después** de que
siscom-api sepa verificar el formato nuevo, y esa condición no es observable desde
admin-api. Mientras el interruptor esté apagado se sigue emitiendo el formato
heredado con la clave dedicada del ADR-004.

### Revocación en los cambios de permiso

Se revoca al cerrar sesión, al retirarle a un usuario el acceso a una unidad y al
desasignar un dispositivo de una unidad (que apaga los enlaces de esa unidad,
porque si el dispositivo se reasigna a otra organización el enlace cruzaría la
frontera).

Estas revocaciones son **best effort**: la autoridad sobre los permisos es
Postgres y el cambio ya ha surtido efecto cuando se llega a revocar; revocar solo
adelanta el momento en que el plano de datos se entera. Si Valkey no responde, el
peor caso es que el alcance viejo viva hasta caducar, y eso no justifica
devolverle un error al usuario por una operación que se completó correctamente.
"Dejar de compartir" es la excepción: ahí la revocación es el único efecto de la
llamada, así que un fallo devuelve 503.

**Hueco conocido, con fecha de revisión.** Al desasignar un dispositivo de una
unidad no se revocan las sesiones de los usuarios que veían esa unidad: no hay
índice por organización y enumerarlos sería caro. Conservan acceso hasta que
caduque su token —acotado por el TTL, pero no cero—. Cerrarlo exigiría un índice
por unidad de las sesiones que la incluyen, con coste de escritura en **cada**
emisión, para ganar diez minutos.

Se acepta hoy y **deja de ser aceptable cuando haya marcas rivales en la
plataforma**: diez minutos de visibilidad sobre un dispositivo recién reasignado
a otra organización es un riesgo que Geminis puede asumir teniendo un solo
operador, pero no uno que se le pueda imponer a un partner que compite con otro
partner. **Revisar antes del primer white-label, no antes.**

### Emisión

`POST /api/v1/auth/data-token`, autenticado con Cognito. Endpoint propio y no
solo el login porque `/auth/refresh` renueva contra Cognito sin pasar por aquí:
un data token que solo naciera en el login caducaría a mitad de sesión sin forma
de renovarlo salvo volviendo a autenticarse. Además el alcance cambia en caliente.

Si falta la clave de firma, Valkey o el secreto del índice de revocación, se
responde **503**. En particular, no se emiten credenciales que no se puedan
revocar.

`/auth/login` adjunta además el data token por conveniencia, para ahorrar un round
trip en el arranque en frío. Ahí la emisión es **best effort** y puede venir a
`null`: el plano de datos no debe poder impedir iniciar sesión. Sin Valkey el
usuario entra y ve la aplicación sin mapa, en vez de no poder entrar.

El sujeto cuyo alcance se calcula y el dueño de la credencial son **parámetros
distintos**. En una sesión de soporte el operador es el dueño pero el alcance es
el del cliente observado; separarlos ahora evita que ese caso se implemente
después como una rama dentro del resolver.

## Consecuencias

### Positivas
- siscom-api no puede aprender el modelo de clientes ni emitir credenciales.
- Revocación inmediata y con un único mecanismo.
- El IMEI deja de viajar al plano de datos.
- Las ventanas de visibilidad se respetan al segundo sin encarecer el caso común.

### Negativas
- siscom-api pasa a depender de Valkey: sin él no sirve datos. Se mitiga con un
  caché en proceso de ≤30 s, acotado además a `min(30 s, exp - ahora)` para no
  sobrevivir al token.
- El navegador maneja dos credenciales (sesión y data token). La complejidad se
  concentra en un único módulo cliente, que hace falta igualmente para la
  reautenticación del WebSocket.
- Cuatro secretos nuevos que configurar, en cuatro ubicaciones cada uno.

### Neutrales
- `mobility.devices` (teléfonos) todavía no tiene `device_ref`. El espacio de
  refs es UUID, así que añadirlo después no colisiona.

## Alternativas consideradas

### Que siscom-api verifique el token de sesión de Cognito
**Descartado**: lleva `sub`, un identificador estable y global de usuario con el
que siscom-api podría correlacionar sesiones y construir perfiles; no dice nada
sobre el alcance, así que obligaría a consultar el modelo de clientes; y sirve
para llamar a admin-api entera, incluida la API interna.

### Meter el alcance en el token en vez de en Valkey
**Descartado**: una flota de miles de dispositivos no cabe en un token que viaja
en query strings; revocar un solo dispositivo obligaría a esperar la caducidad; y
con ventanas horarias un alcance congelado es incorrecto por construcción.

### Un alcance comodín para operadores de plataforma
**Descartado**: invierte la dirección del fallo. En el camino normal un error
deniega; con comodín, un error concede acceso universal. El acceso de soporte se
resuelve como una sesión acotada a un cliente concreto —el patrón de impersonación
de Stripe o Shopify—, que produce una credencial normal y encaja en este contrato
sin tocarlo.

## Referencias

- `app/utils/data_token.py`, `app/services/scope_store.py`,
  `app/services/data_token_issuance.py`, `app/services/access_control.py`
- [ADR-004](./004-separacion-claves-paseto.md)
- [PASETO v4 spec](https://github.com/paseto-standard/paseto-spec)

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-08-21 | 1.0 | Documento inicial |
| 2026-08-21 | 1.1 | Alcance en HASH con traducción a identificador interno; rastro forense por `jti` |
| 2026-08-21 | 1.2 | Índice de revocación separado por propósito; compartir ubicación sobre data token |
| 2026-08-21 | 1.3 | Autorización temporal: el alcance lleva ventanas y el histórico se recorta |
