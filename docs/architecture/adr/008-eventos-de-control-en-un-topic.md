# ADR-008: Los cambios de estado viajan por un solo topic, y cada consumidor elige qué entidades le importan

**Estado:** Propuesto
**Fecha:** 2026-10-19
**Autores:** Equipo de Desarrollo
**Revisores:** -

## Contexto

El 19 de octubre de 2026 las notificaciones push de un iPhone dejaron de llegar.
La causa resultó ser un build de Xcode (`aps-environment = development`), no el
backend, pero recorrer la cadena para descartarlo sacó a la luz dos defectos de
`alert-distributor` que sí son del backend:

1. **Su vista del mundo es una foto del arranque.** `main.rs` carga una vez los
   permisos (qué usuarios ven qué unidad) y los dispositivos activos, y nunca
   los vuelve a leer. El contenedor llevaba seis semanas arriba: cualquier
   usuario, membresía, asignación de unidad o dispositivo posterior era
   invisible para el push y para el WebSocket del mapa, que comparte la caché.
2. **Su regla de visibilidad no es la del API.** Toda persona con una fila en
   `organization_users` recibe las alertas de todas las unidades de esa
   organización: ignora `user_units` y no filtra `status`, así que un miembro
   pausado sigue recibiendo alertas.

Arreglar el primero sin consultar la base periódicamente exige que alguien le
avise de los cambios. Y al revisar qué se publica hoy apareció lo siguiente:

- admin-api ya produce **tres topics de control** —`user-devices-updates`,
  `unit-devices-updates` y `user-units-updates`— con un sobre común
  (`build_control_event`: `event_id`, `event_type`, `entity`, `timestamp`,
  `organization_id`, `data`).
- **Los consumidores existen desde el 04/09/2026, pero a medias.**
  `alert-distributor` `v0.1.9` consume los tres y, con cada evento de unidades,
  vuelve a cargar **toda** la foto de permisos desde la base. `event-processor`
  consume `unit-devices-updates` para aplicar reasignaciones en caliente. En
  producción, a 19/10:
  - `unit-devices-updates` **no existe** en el clúster. El consumidor de
    `event-processor` falla desde su arranque (`GroupAuthorizationFailed`,
    después `TopicAuthorizationFailed`), y el de `alert-distributor` con
    `UnknownTopicOrPartition`. Las reasignaciones solo se ven tras un reinicio.
  - `event-processor` escucha `geofences-update` (singular) y admin-api publica
    en `geofences-updates` (plural). Cuatro geocercas creadas entre el 23/09 y el
    04/10 no se estaban evaluando.
  - `alert-distributor` usa `users.is_master` sobre `users.organization_id`, y
    reparte los dispositivos por cada organización del usuario.
- **Faltan las dos entidades que deciden quién recibe alertas:** las
  membresías (`organization_users`: alta, rol, pausa, reactivación, baja) y el
  estado del usuario (`users.status`: baja y readmisión desde la 029). Ningún
  topic las lleva.
- **La foto de arranque se lee directo de las tablas de admin-api, y una
  migración la rompió sin que nadie lo notara.** La 036 (v1.49.0, 02/10)
  renombró `users.organization_id`. La consulta de permisos de
  `alert-distributor` dejó de funcionar ese día, pero el contenedor llevaba
  arriba desde el 05/09 y no volvió a ejecutarla. El siguiente reinicio habría
  dejado a todos sin alertas. Se detectó el 19/10 y se corrigió en
  `alert-distributor` `v0.2.0` (#3). Ningún test de admin-api podía verlo:
  el esquema que leen los consumidores no estaba escrito en ningún lado.

En términos de patrones, esto ya es **coreografía con modelos de lectura
(CQRS)**: admin-api es el lado de escritura y publica hechos; cada consumidor
reacciona por su cuenta y mantiene en memoria su propio modelo de lectura (la
caché de destinatarios del distribuidor, el resolver de unidades de
event-processor). Nadie orquesta. La debilidad conocida de la coreografía es que
nadie ve el flujo completo, y es exactamente lo que pasó: tres piezas
desalineadas durante semanas sin que nada avisara.

El patrón que trajo hasta aquí es un topic por necesidad: cada vez que un
consumidor necesitaba una entidad, se abría un topic, un usuario y un par de
ACL, y cada pieza se configuraba por separado en el código, en el clúster y en
cada servicio. Tres de esas piezas quedaron desalineadas sin que nada fallara
de forma visible. Esta necesidad pediría al menos dos topics más.

## Decisión

### 1. Un solo topic, `control-plane-events`, para cambios de estado de entidades

Todo cambio de estado de una entidad que otro servicio necesite **reflejar** se
publica en `control-plane-events`. Cada consumidor lee el topic completo y
descarta por `entity` lo que no le afecta. Añadir una entidad nueva es añadir un
valor de `entity` y documentarlo en el contrato; no se crea topic ni ACL.

Entran, en la primera versión: `user`, `organization_user`, `user_unit`,
`unit_device` y `user_device`.

**No entran**, y la frontera es deliberada:

- **Telemetría** (`mobility-locations-raw` y similares). Otro volumen y otro
  ritmo; mezclarla obligaría a cada consumidor de control a leer el tráfico GPS
  para descartarlo.
- **Las reglas** (`alert-rules-updates`, `geofences-updates`,
  `team-rules-updates`). Ya tienen contrato y consumidores propios
  (alert-processor, event-processor). Pueden migrar después; este ADR no lo
  exige.

### 2. Cada evento lleva el estado completo de la fila, no un delta

`event_type` es `UPSERT` (la fila existe con este estado) o `DELETE` (la fila ya
no existe). Un consumidor que aplique los eventos en orden converge al estado
real aunque vea alguno dos veces, sin necesidad de guardar historia ni de
comparar versiones.

El sobre actual se conserva y se le añade `schema_version` (entero, empieza en
`1`). El detalle de cada `data` vive en el contrato, no aquí:
[`eventos-de-control.md`](../eventos-de-control.md).

### 3. Una partición, y la key es `"{entity}:{id}"`

El volumen de control son altas, asignaciones y registros de dispositivos:
decenas al día. Con una partición el orden es **total**, no solo por key — el
alta de una membresía y la asignación de unidad que la sigue llegan en el orden
en que ocurrieron. La key no ordena nada con una partición; existe para que
activar compaction más adelante conserve el último estado de cada entidad.

Retención: la del clúster. Ningún consumidor depende de releer la historia
(ver §4).

### 4. Los consumidores arrancan de una foto y luego solo escuchan

Ningún consumidor vuelve a consultar la base después de arrancar. La secuencia
es:

1. Anotar el offset final de `control-plane-events`.
2. Leer la base una vez (la foto).
3. Consumir desde el offset anotado en el paso 1.

Los eventos ocurridos entre 1 y 2 se aplican sobre una foto que ya los
contiene; como llevan estado completo y llegan en orden, el resultado converge.
El consumidor **no hace commit** de offsets ni necesita grupo: cada arranque
empieza de su foto. Eso evita también la ACL de grupo.

Cada evento se aplica **sobre la entrada que cambia**. Volver a cargar la foto
completa por cada evento, como hace hoy `alert-distributor`, es sondear la base
con otro disparador.

### 4b. La foto se lee de vistas que admin-api mantiene, no de sus tablas

El incidente de la 036 muestra que la foto de arranque es parte del contrato
aunque nadie la haya escrito. Por eso admin-api publica, por migración, una
vista por entidad con las mismas columnas que el `data` del evento:

- `control_plane.user`
- `control_plane.organization_user`
- `control_plane.user_unit`
- `control_plane.unit_device`
- `control_plane.user_device`

Viven en un esquema propio, y la lectura es un `GRANT SELECT` sobre ese esquema
para el usuario de cada consumidor. A partir de aquí:

- Una migración que renombre o quite una columna de las tablas tiene que
  mantener viva la vista. Si no puede, sube `schema_version` de la entidad,
  igual que en el topic.
- Un test de esquema de admin-api, sobre la base migrada
  (`esquema_desechable`), comprueba que cada vista existe y tiene exactamente
  las columnas del contrato. La próxima 036 falla en la CI de admin-api, no en
  el arranque de otro servicio.
- La regla de visibilidad (§6) **no** va en las vistas. Cada consumidor la
  aplica sobre los datos; las vistas solo exponen filas.

### 5. Se publica después del commit, sin outbox, y se acepta que un evento puede perderse

admin-api publica cuando la transacción ya confirmó, y `publish_control_event`
no propaga el fallo: lo registra y responde. El orden es deliberado: un evento
que falta deja a un consumidor desactualizado, pero uno que sobra —publicado
antes de un commit que luego falla— le concede algo que nunca existió.

Para cubrir el caso real, que es un fallo transitorio de Kafka, la publicación
es **síncrona y reintenta** unas pocas veces con backoff antes de rendirse (hoy
es un único intento con `flush(timeout=3)`). Lo que queda sin cubrir es que
Kafka siga caído después de los reintentos, o que el proceso muera entre el
commit y el envío. En ese caso, el cambio queda en la base y el evento no sale.
El consumidor queda desfasado hasta su siguiente arranque, que lo corrige por
construcción (§4), o hasta una reconciliación a demanda.

Se acepta por ahora. **El outbox transaccional es el siguiente paso decidido**,
no una posibilidad: se hace en un PR propio después de la adopción. Mientras
tanto, cada fallo deja `control_event_publish_failed` en el log con la entidad y
la key, para medir cuánto se pierde.

Dos peticiones concurrentes pueden confirmar en un orden y publicar en el otro.
Es la misma clase de riesgo y tiene el mismo remedio.

### 6. La visibilidad de un consumidor sale de la membresía, no de `users.is_master`

El API decide qué unidades ve una sesión en `access_control.subject_for_user`:
si `users.is_master`, todas las de la organización **activa**; si no, las de
`user_units`. Un consumidor como `alert-distributor` no tiene organización
activa —alerta a todas las de la persona a la vez— y `is_master` es un atributo
del usuario, no de la membresía (`register_user` lo pone en `true` a todo el que
se registra). Copiar la regla le daría a un maestro todas las unidades de **cada**
organización donde tenga una membresía.

Por eso, para un consumidor, la regla es:

- **Membresía `owner`** → todas las unidades de esa organización.
- **Cualquier otro rol** → solo las unidades de `user_units` dentro de esa
  organización.
- Sin efecto si la membresía no está `ACTIVE` o si `users.status` no está
  `ACTIVE`. Reactivar cualquiera de las dos devuelve el acceso.

El rol `owner` no se puede asignar ni quitar por API (`OrganizationService`
lo prohíbe), así que coincide con quien se registró y es maestro en su
organización. Verificado en producción el 19/10/2026: ninguna fila tiene
`is_master` en su organización por defecto sin ser `owner`, ni `owner` sin ser
maestro. El cambio de regla no le quita nada a ningún owner.

### 7. Los tres topics actuales se retiran cuando sus consumidores migren

admin-api escribe **a la vez** en `control-plane-events` y en los dos topics
viejos que existen (`user-devices-updates`, `user-units-updates`) hasta que
`alert-distributor` lea el nuevo. `unit-devices-updates` no existe en el
clúster, así que no hay nada que mantener. Cuando ningún consumidor lea un topic
viejo, admin-api deja de escribirlo y se borra junto con sus grupos y ACL.

### 8. Un usuario de Kafka por servicio, no por propósito

admin-api produce con `alerts-rules-producer`, que hoy escribe seis topics y
solo uno es de reglas. El topic nuevo se autoriza a un usuario
**`siscom-admin-api`**. Así, una ACL dice qué servicio escribe, y el nombre
sigue siendo cierto aunque admin-api publique otra cosa mañana. La migración del
resto de permisos de admin-api a ese usuario va en la limpieza del clúster
(«Adopción», paso 6).

### 9. Un consumidor que no puede leer no se declara sano

`event-processor` pasó seis semanas con `GroupAuthorizationFailed` y
`TopicAuthorizationFailed` en el log, y su contenedor seguía `healthy`. En
coreografía nadie más lo va a notar, así que cada consumidor de
`control-plane-events`:

- **Falla al arrancar** si no puede leer el topic o su foto. Un error de
  autorización o un topic inexistente no se registra y se sigue: el proceso
  termina, y el despliegue lo muestra.
- **Lo refleja en su health check** si deja de recibir después de arrancar: el
  estado del consumidor de control forma parte de `healthy`.
- **Reporta su atraso**: el offset aplicado frente al final del topic, en la
  línea de métricas que ya escribe cada minuto.

Una alerta sobre esas tres señales es la defensa que la coreografía no trae
sola.

## Consecuencias

### Positivas

- Un servicio nuevo que necesite estado de control pide una ACL de lectura
  sobre un topic, no un topic por entidad.
- `alert-distributor` deja de necesitar reinicios para ver usuarios,
  membresías, asignaciones y dispositivos nuevos, sin consultar la base.
- El push y el WebSocket del mapa pasan a respetar `user_units`, las pausas y
  las bajas, igual que el API.
- `event-processor` recibe por fin las reasignaciones, y deja de consultar la
  base por cada IMEI sin asignar.
- Un rename en admin-api ya no puede romper el arranque de otro servicio sin
  fallar antes en su propia CI (§4b).

### Negativas

- Cada consumidor recibe eventos que no le interesan. Con el volumen de control
  es irrelevante; sería un problema si alguien intentara meter telemetría aquí
  (§1 lo prohíbe).
- Un evento perdido desfasa a los consumidores hasta su siguiente arranque (§5).
- El cambio de regla de visibilidad (§6) quita alertas a quien hoy las recibe
  sin tener la unidad asignada. Es lo correcto, pero es un cambio visible para
  usuarios.

### Neutrales

- La regla de §6 diverge de `subject_for_user` a propósito. Esa función tiene
  el mismo defecto con el selector de cuenta (un maestro que actúa en otra
  organización ve todas sus unidades), pero corregirlo es otro cambio y otro PR.

## Alternativas consideradas

### Un topic por entidad (seguir como hasta ahora)

**Descartado** porque cada necesidad nueva cuesta un topic, un usuario, ACL y
configuración en cada consumidor. Además, una membresía y la asignación de
unidad que la acompaña viajarían por topics distintos, sin orden entre ellos.

### Recargar la foto periódicamente en el consumidor

**Descartado.** Es lo más simple, pero convierte a cada consumidor en un cliente
de sondeo de la base, y el costo crece con cada consumidor nuevo y con cada
réplica. Ya existe Kafka para avisar de cambios.

### Publicar en Kafka antes del commit

**Descartado.** Escribir en la transacción, publicar, esperar el ack y después
confirmar garantiza que ningún cambio confirmado se quede sin evento, pero:

- Si el commit falla **después** de publicar (una restricción al confirmar, un
  deadlock, una conexión perdida o el proceso muere), los consumidores aplican
  algo que nunca ocurrió. En el plano de control eso es una concesión
  fantasma: una membresía revertida sigue recibiendo alertas. `flush()` antes
  de publicar reduce el riesgo, pero no lo elimina.
- Las escrituras de admin-api pasan a depender de Kafka. Con Redpanda en un solo
  nodo, réplica 1 y en el mismo host, cada reinicio o actualización del broker
  sería una ventana en la que no se puede registrar un dispositivo, invitar ni
  asignar unidades.
- La transacción sigue abierta, con sus bloqueos, mientras se espera el ack.
- No mejora el orden entre peticiones concurrentes.

Cambia «a veces falta un evento» por «a veces sobra uno, y las escrituras
dependen del broker». Para este dominio es peor.

### Event-first («escúchate a ti mismo»)

**Descartado.** admin-api solo publicaría, y un consumidor propio escribiría en
la base. Garantiza la consistencia, pero reescribe cómo escribe admin-api, y la
API ya no puede devolver en la respuesta lo que acaba de guardar.

### Outbox transaccional en admin-api

**Decidido como siguiente paso, en un PR propio después de la adopción.**

Se inserta el evento en una tabla `outbox_events` en la misma transacción que el
cambio. El mismo proceso lo envía justo después del commit, reintenta con backoff
mientras haya pendientes, y al arrancar envía lo que quedó. Usa `FOR UPDATE SKIP
LOCKED` para que dos workers no envíen la misma fila. Garantiza que nada
confirmado se pierda y que nada no confirmado salga, sin sondear la base.

No entra en la adopción para no retrasar los arreglos que ya están rotos en
producción, y porque con la emisión centralizada (contrato, «Regla de
implementación») se vuelve un cambio interno de esa función más el relay: los
consumidores no se enteran. Con el outbox en su sitio se puede pasar a
compaction (ver abajo) y retirar las vistas de §4b. Si se quiere un relay sin
proceso propio, la evolución es leer el WAL de la tabla outbox (log tailing).

### CDC sobre las tablas de negocio (Debezium o replicación lógica)

**Descartado.** Publicar `users`, `organization_users`, etc. tal cual leyendo el
WAL convertiría el esquema de las tablas en el contrato, que es justo lo que
rompió la 036. Además es otra pieza que operar: un slot de replicación retiene
WAL mientras su lector esté caído y puede llenar el disco de la base.

Leer el WAL **de una tabla outbox** (outbox + log tailing) sí es una evolución
válida del outbox: el contrato lo sigue escribiendo el código y el lector solo
transporta. Tiene sentido si el relay en proceso se queda corto.

### Saga y orquestación

**No aplican.** Una saga coordina una operación que escriben varios servicios,
con compensaciones. Aquí admin-api es el único que escribe estas entidades y los
consumidores solo replican estado. Una saga, además, también necesitaría un
outbox para no perder sus propios eventos.

### Event sourcing

**Descartado.** Hacer del evento la fuente de verdad resolvería la doble
escritura de raíz, pero implica reescribir cómo admin-api guarda todo. El costo
es desproporcionado para el problema.

### Reconciliación periódica

**Descartada como mecanismo principal**: corrige después, no garantiza, y
ejecutada por cron es otra forma de sondeo. **Aceptada a demanda**, como
comando que republica el estado actual de todas las filas: sirve para reparar,
para recrear el topic y como carga inicial si algún día se activa compaction.

### Compaction desde el inicio

**Aplazado hasta después del outbox.** Permitiría a un consumidor reconstruir el
estado leyendo el topic desde el principio, sin foto. Pero obliga a que ningún
evento se pierda (lo que da el outbox), a publicar un estado inicial de todas las
filas (la reconciliación a demanda) y a emitir cada `DELETE` también como
*tombstone* (valor nulo) para que la key desaparezca. La key
`"{entity}:{id}"` ya está pensada para eso.

## Adopción

0. ~~Hotfix de `alert-distributor`: la foto usa `default_organization_id`.~~
   `v0.2.0`, en producción el 19/10/2026.
1. Crear el topic, el usuario `siscom-admin-api` y las ACL (comandos en el
   contrato).
2. admin-api: vistas `control_plane.*` con su test de esquema (§4b), y
   emisión de las cinco entidades en `control-plane-events`, manteniendo los
   dos topics viejos que existen (§7).
3. **event-processor**, el primero en migrar porque es el cambio más chico y
   cierra la atribución equivocada de eventos tras una reasignación: lee
   `unit_device` del topic nuevo y su foto de `control_plane.unit_device`. En la
   misma versión, geocercas: escucha `geofences-updates` (plural) con su propio
   grupo, separado de `events-processor-group`.
4. **alert-distributor**: consumidor de control, foto desde las vistas, caché
   indexada para aplicar cada evento sobre su entrada, dispositivos por persona y
   regla de §6. En la misma versión, clasificar los errores de SNS por tipo (hoy
   `to_string()` devuelve `"service error"` y ningún endpoint muerto se
   desactiva).
5. admin-api deja de escribir los topics viejos.
6. Limpieza del clúster: borrar los topics viejos, `geofences-update`
   (singular), sus grupos y las ACL huérfanas, y pasar el resto de permisos de
   admin-api al usuario `siscom-admin-api`.
7. **Outbox transaccional** en admin-api (ver «Alternativas»). Después, si se
   quiere, compaction y retiro de las vistas `control_plane.*`, en otro ADR.

## Referencias

- Contrato de mensajes: [`eventos-de-control.md`](../eventos-de-control.md)
- `app/services/messaging/control_events.py` (sobre actual)
- `app/services/access_control.py` (`subject_for_user`)
- `alert-distributor/src/permissions/loader.rs` y `src/kafka/updates.rs`
  (`v0.2.0`: las fotos y la recarga por evento de hoy)
- `event-processor/src/unit_devices/mod.rs` y `src/kafka/mod.rs`
- `alert-distributor#3`: el hotfix de la columna renombrada

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-10-19 | 1.0 | Documento inicial |
