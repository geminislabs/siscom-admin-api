"""
Materialización del alcance del data token en Valkey.

MODELO
======
El token solo lleva un `scope_ref` opaco. El conjunto de identificadores que ese
alcance permite vive aquí:

    dt:scope:<scope_ref>:dev   → HASH device_ref → {"id": ..., "windows": [...]}
    dt:scope:<scope_ref>:unit  → HASH unit_ref    → {"id": ..., "windows": [...]}

admin-api escribe; siscom-api solo lee, con `HGET`, que en una sola operación
resuelve **autorización, traducción y vigencia**: el campo ausente (`nil`) es la
denegación, y el valor trae el identificador con el que consultar sus tablas
junto con las ventanas en que ese permiso existió. Así el plano de datos no
necesita llamar aquí en el camino caliente ni migrar sus tablas para dejar de
indexar por IMEI.

La ventana viaja con la referencia porque siscom-api no puede deducirla: hacerlo
exigiría conocer el modelo de unidades y asignaciones, que es justo lo que no
debe aprender. `"to": null` significa ventana abierta, y es lo único que autoriza
los datos en vivo.

Una clave o un campo ausentes son **denegar**: la ausencia ES la revocación, y
por eso revocar es un `DEL` y no hay una segunda lista de tokens revocados que
pueda divergir.

Que el `device_id` figure como valor no rompe el aislamiento: siscom-api ya tiene
todos los IMEIs, sus tablas están indexadas por ellos. El ref existe para que el
IMEI no llegue al navegador ni a los logs. Lo que el plano de datos sigue sin
poder saber es de quién es cada flota.

ÍNDICE INVERSO
==============
`DEL` necesita saber qué borrar. `dt:owner:<propósito>:<h>` guarda los
`scope_ref` vivos de un sujeto, para poder revocarlos todos cuando cambian sus
permisos.

El **propósito** separa credenciales que no deben morir juntas. Los enlaces de
compartir ubicación pertenecen a quien los generó, igual que su sesión; sin esta
separación, renovar el data token de la sesión —que revoca lo anterior del mismo
dueño— apagaría de paso todos los enlaces que esa persona tuviera compartidos.
Cambiar los permisos de alguien debe revocar su sesión, no lo que compartió
deliberadamente.

`<h>` es un HMAC del identificador del sujeto, no el identificador. El índice es
lo único de este espacio que relaciona alcances con personas, y Valkey es
compartido con siscom-api: si la ACL que le restringe a `dt:scope:*` se despliega
mal, con la clave en claro siscom-api aprendería identidades de usuario. Con HMAC
no aprende nada aunque la lea. Es la medida que sobrevive a un error de
configuración, y por eso no es opcional.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from enum import Enum
from typing import Iterable, List, Mapping, Optional, Protocol
from uuid import UUID

from app.core.config import settings

logger = logging.getLogger(__name__)

SCOPE_PREFIX = "dt:scope"
OWNER_PREFIX = "dt:owner"
JTI_PREFIX = "dt:jti"


class ScopeStoreUnavailable(RuntimeError):
    """Valkey no está configurado o no responde."""


class RevocationIndexNotConfigured(RuntimeError):
    """
    Falta `DATA_TOKEN_INDEX_SECRET_B64`.

    Sin él no se pueden derivar las claves del índice inverso, es decir, no se
    puede revocar. Emitir credenciales que no se pueden revocar es peor que no
    emitirlas, así que esto bloquea la emisión en vez de degradarla.
    """


class SupportsWire(Protocol):
    """Lo que el store necesita de una concesión: saber serializarse."""

    def to_wire(self) -> dict: ...  # noqa: D102


def _encode(grants: Mapping[UUID, "SupportsWire"]) -> dict:
    """
    Serializa las concesiones al formato de cable.

    Separadores compactos porque cada valor es un campo de hash y un dispositivo
    con varias ventanas se repite por cada alcance vivo.
    """
    return {
        str(ref): json.dumps(grant.to_wire(), separators=(",", ":"))
        for ref, grant in grants.items()
    }


class ValkeyClient(Protocol):
    """
    Lo mínimo que usamos de un cliente Valkey/Redis.

    Se declara como Protocol para que el store no dependa del paquete `redis` en
    tiempo de import: los tests inyectan un doble y el despliegue inyecta el
    cliente real.
    """

    def pipeline(self): ...  # noqa: D102
    def delete(self, *keys: str) -> int: ...  # noqa: D102
    def smembers(self, key: str) -> Iterable[bytes]: ...  # noqa: D102
    def srem(self, key: str, *values: str) -> int: ...  # noqa: D102


def _index_secret() -> bytes:
    raw = settings.DATA_TOKEN_INDEX_SECRET_B64
    if not raw:
        raise RevocationIndexNotConfigured(
            "DATA_TOKEN_INDEX_SECRET_B64 no está configurada"
        )
    return base64.b64decode(raw, validate=True)


class ScopePurpose(str, Enum):
    """
    Para qué se emitió una credencial. Determina con qué otras se revoca en bloque.
    """

    SESSION = "session"
    SHARE = "share"


def owner_key(subject_id: UUID, purpose: ScopePurpose = ScopePurpose.SESSION) -> str:
    """Clave del índice inverso para un sujeto y propósito, no invertible."""
    digest = hmac.new(
        _index_secret(),
        f"{purpose.value}:{subject_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"{OWNER_PREFIX}:{purpose.value}:{digest}"


def scope_keys(scope_ref: UUID) -> tuple[str, str]:
    return (
        f"{SCOPE_PREFIX}:{scope_ref}:dev",
        f"{SCOPE_PREFIX}:{scope_ref}:unit",
    )


def jti_key(jti: UUID) -> str:
    """Clave del rastro forense de un token concreto."""
    return f"{JTI_PREFIX}:{jti}"


class ScopeStore:
    """Escritura y revocación de alcances. No lee: quien lee es siscom-api."""

    def __init__(self, client: Optional[ValkeyClient]) -> None:
        self._client = client

    @property
    def client(self) -> ValkeyClient:
        if self._client is None:
            raise ScopeStoreUnavailable("VALKEY_URL no está configurada")
        return self._client

    @property
    def is_configured(self) -> bool:
        return self._client is not None

    def write_scope(
        self,
        scope_ref: UUID,
        *,
        subject_id: UUID,
        devices: Mapping[UUID, "SupportsWire"],
        units: Mapping[UUID, "SupportsWire"],
        token_ttl_seconds: int,
        jti: Optional[UUID] = None,
        purpose: ScopePurpose = ScopePurpose.SESSION,
    ) -> None:
        """
        Materializa un alcance y lo registra en el índice inverso del sujeto.

        El TTL de las claves excede al del token en `VALKEY_SCOPE_TTL_MARGIN_SECONDS`
        para que el alcance no desaparezca por debajo de un token aún válido.

        Todo va en una única pipeline: un alcance a medias escrito sería un
        alcance más estrecho de lo debido —falla cerrado— pero también un token
        que no funciona, y prefiero que no exista a que exista roto.

        Si se pasa `jti`, se deja además un rastro `dt:jti:<jti>` → clave de
        dueño. siscom-api registra el `jti` en sus logs de acceso sin saber de
        quién es; cruzándolo con este rastro se reconstruye a quién pertenecía un
        acceso concreto. Ninguno de los dos lados por separado identifica a
        nadie: el valor guardado es la clave HMAC, no el usuario.

        La auditoría permanente (`AuditService`) se reserva para las sesiones de
        soporte. Un registro por cada refresco de diez minutos de cada usuario
        sería ruido sin valor forense; este rastro caduca con el alcance, que es
        justo la ventana en la que la forense sirve para reaccionar.
        """
        dev_key, unit_key = scope_keys(scope_ref)
        index_key = owner_key(subject_id, purpose)
        ttl = token_ttl_seconds + settings.VALKEY_SCOPE_TTL_MARGIN_SECONDS

        pipe = self.client.pipeline()
        if devices:
            pipe.hset(dev_key, mapping=_encode(devices))
            pipe.expire(dev_key, ttl)
        if units:
            pipe.hset(unit_key, mapping=_encode(units))
            pipe.expire(unit_key, ttl)

        pipe.sadd(index_key, str(scope_ref))
        pipe.expire(index_key, ttl)

        if jti is not None:
            pipe.set(jti_key(jti), index_key, ex=ttl)

        pipe.execute()

    def revoke_scope(self, scope_ref: UUID) -> None:
        """Revoca un alcance concreto. La ausencia de la clave es la denegación."""
        self.client.delete(*scope_keys(scope_ref))

    def revoke_all_for_subject(
        self, subject_id: UUID, purpose: ScopePurpose = ScopePurpose.SESSION
    ) -> List[UUID]:
        """
        Revoca todos los alcances vivos de un sujeto y devuelve cuáles eran.

        Es lo que hay que llamar cuando se estrechan los permisos —desasignar
        una unidad, perder una membresía, cerrar sesión—. Para la sesión lo hace
        `app/services/session_revocation.py` desde el ORM; emitir ya no revoca.

        Solo revoca el propósito indicado. Renovar la sesión no apaga los enlaces
        que esa persona haya compartido: son credenciales distintas con vidas
        distintas.
        """
        index_key = owner_key(subject_id, purpose)
        raw = self.client.smembers(index_key) or []

        refs: List[UUID] = []
        for item in raw:
            value = item.decode("utf-8") if isinstance(item, bytes) else str(item)
            try:
                refs.append(UUID(value))
            except ValueError:
                # Entrada corrupta: se ignora para el resultado, pero se borra
                # igualmente junto con el índice.
                logger.warning("scope_ref no válido en %s: %r", index_key, value)

        # Los rastros `dt:jti` NO se borran aquí: caducan solos, y conservarlos
        # permite investigar el uso de un token *después* de revocarlo, que es
        # precisamente cuando interesa.
        keys: List[str] = []
        for ref in refs:
            keys.extend(scope_keys(ref))
        if keys:
            self.client.delete(*keys)
        self.client.delete(index_key)

        return refs


def build_client() -> Optional[ValkeyClient]:
    """
    Cliente real a partir de `VALKEY_URL`, o None si no está configurada.

    El import de `redis` es perezoso a propósito: el paquete solo hace falta en
    los entornos que tengan Valkey, y así los tests no lo necesitan.
    """
    if not settings.VALKEY_URL:
        logger.warning(
            "VALKEY_URL no está configurada: la emisión de data tokens responderá 503."
        )
        return None

    import redis  # noqa: PLC0415

    return redis.Redis.from_url(settings.VALKEY_URL)
