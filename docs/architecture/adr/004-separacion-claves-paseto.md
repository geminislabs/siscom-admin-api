# ADR-004: Separación de claves PASETO (servicio interno vs. compartir ubicación)

**Estado:** Propuesto
**Fecha:** 2026-08-20
**Autores:** Equipo de Desarrollo
**Revisores:** -

## Contexto

`app/utils/paseto_token.py` emitía dos familias de tokens con **una sola clave**
PASETO v4.local (`PASETO_SECRET_KEY`):

1. **Tokens de compartir ubicación** (`scope: public-location-share`), emitidos en
   `POST /api/v1/units/{unit_id}/share-location`.
2. **Tokens de servicio interno** (`scope: internal-gac-admin`,
   `internal-nexus-admin`, `internal-app-admin`), emitidos en
   `POST /api/v1/auth/internal` y aceptados por `get_auth_cognito_or_paseto`
   (`app/api/deps.py`) para toda la API de `app/api/v1/endpoints/internal/`.

PASETO v4.local es **simétrico**: quien puede verificar un token también puede
firmarlo. Los tokens de compartir ubicación no se verifican en este servicio
—no existe ningún llamador de `decode_share_token` en el repositorio— sino en
**siscom-api**, que por tanto necesita la clave.

Se confirmó que siscom-api tiene `PASETO_SECRET_KEY` en su configuración y la
usa con `Key.new(version=4, purpose="local", ...)`. La consecuencia es directa:
**siscom-api podía emitir tokens `internal-gac-admin` y operar contra la API
interna de admin-api con privilegios de administrador.** No es un riesgo
hipotético ni exclusivo del escenario multi-tenant; es una escalada de
privilegios en el sistema tal y como está desplegado.

Este ADR cubre la mitigación inmediata. El rediseño completo del plano de datos
(PASETO v4.public con Ed25519, scope resuelto en Valkey, identificadores opacos)
es la Fase 1 del proyecto multi-tenant y se documenta aparte.

## Decisión

**Cada familia de tokens usa su propia clave.**

- `PASETO_SECRET_KEY` → exclusivamente tokens de servicio interno. No sale de
  este servicio.
- `SHARE_LOCATION_KEY_B64` → exclusivamente tokens de compartir ubicación. Es la
  única que se entrega a siscom-api.

Decisiones de detalle:

1. **Sin degradación silenciosa.** Si falta `SHARE_LOCATION_KEY_B64` no se
   recurre a `PASETO_SECRET_KEY`: se lanza `ShareLocationKeyNotConfigured` y el
   endpoint de compartir responde `503`. Un fallback habría reintroducido en
   silencio justo la vulnerabilidad que este cambio elimina.

2. **Fallo acotado, no fallo total.** La clave se resuelve de forma perezosa, de
   modo que su ausencia deshabilita solo compartir ubicación en lugar de impedir
   el arranque de la API. Una clave *presente pero inválida* sí falla al
   construir, porque es un error de configuración que conviene ver al arrancar.

3. **Validación estricta de la clave nueva**: exactamente 32 bytes tras decodificar
   base64, y se rechaza la clave de todo ceros de `.env.example`. El
   relleno/truncado histórico (`ljust(32, b"\0")`) se conserva **solo** para
   `PASETO_SECRET_KEY`, para no invalidar los tokens de servicio ya emitidos ni
   arriesgar el arranque en producción; ahora emite un aviso por log y queda
   pendiente de una rotación planificada.

4. **Se elimina `decode_any_token`.** Validaba la expiración pero no el scope, de
   modo que un token de compartir podía pasar por uno de servicio. No tenía
   llamadores; se borra en vez de heredarse al diseño nuevo.

5. **Convención de nombres**: ninguna clave nueva se llama `PASETO_*`. Ese
   prefijo queda reservado al secreto de servicio heredado, para que no vuelvan
   a mezclarse dos sistemas distintos por parecerse el nombre.

## Consecuencias

### Positivas
- siscom-api deja de poder firmar credenciales administrativas.
- Las dos claves pueden rotarse por separado y con distinta frecuencia.
- Prepara la migración a v4.public: el punto de corte entre "clave de servicio" y
  "clave de datos" ya está hecho, y solo cambia el material criptográfico.
- Las propiedades de seguridad quedan fijadas por tests, no por convención.

### Negativas
- Exige un despliegue coordinado con siscom-api (ver Secuencia). Mal ordenado,
  compartir ubicación deja de funcionar.
- Un secreto más que gestionar en los cuatro puntos de configuración
  (`.env.example`, `docker-compose.yml`, `docker-compose.prod.yml` y el bloque
  `env:` **más** la lista `envs:` de `.github/workflows/deploy.yml`).

### Neutrales
- El formato del token de compartir no cambia: sigue siendo v4.local con el mismo
  payload. Solo cambia la clave con la que se firma.
- `PASETO_SECRET_KEY` sigue con relleno/truncado; se corrige en la rotación.

## Secuencia de despliegue

> **SUPERADA ANTES DE EJECUTARSE — ver [ADR-005](./005-data-token-plano-de-datos.md).**
>
> Esta secuencia nunca llegó a desplegarse. siscom-api confirmó que
> `SHARE_LOCATION_KEY_B64` está implementada en ambos servicios pero **no se ha
> configurado en ningún entorno**: hoy compartir ubicación se verifica, si se
> verifica, con `PASETO_SECRET_KEY` a secas.
>
> Mientras tanto, ADR-005 llevó los tokens de compartir a PASETO v4.public
> (Ed25519), donde el verificador **no puede firmar en absoluto**. Eso no
> sustituye a esta medida puente: la vuelve innecesaria. Configurar ahora una
> clave simétrica intermedia sería crear, distribuir y retirar un secreto cuyo
> único propósito es ser desechado unos días después.
>
> **Recomendación: saltarse los pasos 2 y 3 e ir directamente a v4.public**
> (`SHARE_LOCATION_USE_DATA_TOKEN=true`), con lo que se llega antes al paso 4,
> que es el único que cierra la escalada.
>
> El código de separación de claves **se conserva**: es el camino de respaldo si
> hubiera que apagar el interruptor de v4.public, y el aislamiento entre la clave
> de servicio y la de compartir sigue siendo correcto por sí mismo.

El orden importa, porque el emisor cambia de clave y el verificador vive en otro
servicio. Los tokens de compartir caducan a los 30 minutos, así que basta una
ventana de aceptación breve.

1. **siscom-api** despliega aceptando **ambas** claves (la vieja y la nueva).
2. Se configura `SHARE_LOCATION_KEY_B64` en los secretos de ambos servicios.
3. **admin-api** despliega y empieza a firmar con la clave nueva.
4. Pasados >30 minutos, **siscom-api** deja de aceptar la vieja y **elimina
   `PASETO_SECRET_KEY` de su entorno**. Este paso es el que cierra la escalada;
   los anteriores solo lo hacen posible.
5. Se rota `PASETO_SECRET_KEY` en admin-api, dando por comprometida la anterior.

Si `SHARE_LOCATION_KEY_B64` se configura en el mismo despliegue en que entra este
código, la ventana de indisponibilidad de compartir ubicación es nula.

## Alternativas consideradas

### Ir directamente a v4.public (Ed25519) sin paso intermedio
**Descartado** porque exige coordinar el cambio de formato, la generación del par
de claves, los identificadores opacos y el despliegue de tres servicios. Son días.
La escalada de privilegios está activa hoy y separar dos claves simétricas se
resuelve en horas sin bloquear la migración posterior.

### Mantener una sola clave y restringir por scope en el verificador
**Descartado** porque no arregla nada: quien tiene la clave puede firmar un token
con el scope que quiera. La validación de scope en el verificador solo sirve si el
firmante es de confianza, y aquí el problema es precisamente que el verificador
puede firmar.

### Fallback a `PASETO_SECRET_KEY` cuando falta la clave nueva
**Descartado** porque un despliegue que olvidara el secreto seguiría funcionando
—en apariencia— con la vulnerabilidad intacta y sin señal alguna. Preferimos un
`503` visible y corregible en minutos.

## Referencias

- `app/utils/paseto_token.py` — emisión y verificación
- `app/api/deps.py` — `get_auth_cognito_or_paseto`, consumidor de los tokens de servicio
- `app/api/v1/endpoints/units.py` — `POST /units/{unit_id}/share-location`
- `docs/security/threat-model.md`
- [PASETO v4 spec](https://github.com/paseto-standard/paseto-spec)

## Registro de cambios

| Fecha | Versión | Cambios |
|-------|---------|---------|
| 2026-08-20 | 1.0 | Documento inicial |
| 2026-08-21 | 1.1 | La secuencia de despliegue queda superada por ADR-005 antes de ejecutarse: `SHARE_LOCATION_KEY_B64` nunca se configuró en ningún entorno |

---

## Actualización · 22 de septiembre de 2026

El endpoint `POST /api/v1/auth/internal` que este ADR cita como emisor de los tokens de
servicio **se eliminó**. No se edita el cuerpo de arriba a propósito: un ADR registra una
decisión en su momento, y reescribirlo borraría el rastro de por qué las cosas fueron así.

Lo que cambia respecto a lo que dice el texto original: los tokens de servicio ya no se emiten
por HTTP desde esta API. GAC los firma en su propio proceso (`create_app_token`), y
`/internal/*` los acepta con `get_auth_solo_servicio`, que **no** admite Cognito — a diferencia
de `get_auth_cognito_or_paseto`, que es lo que este ADR menciona y lo que resultó ser el
agujero. Ver `docs/security/plano-de-control-abierto.md`.
