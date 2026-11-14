"""
Emisión de data tokens: junta resolución de alcance, Valkey y firma.

El orden de los pasos no es incidental:

1. Se resuelve el alcance del sujeto en identificadores opacos.
2. Se materializa el alcance bajo un `scope_ref` recién generado. Nunca se
   reescribe un ref existente: mutar un SET en uso deja que un lector lo observe
   a medias, y con ref nuevo por emisión el alcance de cada token es inmutable.
3. Se firma el token, que solo lleva ese ref y una ventana temporal.

Emitir **no revoca** los tokens anteriores del sujeto (D1, 06/11/2026). Antes
lo hacía, y dos emisiones seguidas del mismo usuario —la web y el móvil, o dos
refresh que se cruzan— se mataban entre sí. Lo que garantiza que estrechar
permisos surta efecto ya es `app/services/session_revocation.py`, que revoca
desde el ORM al confirmar cualquier cambio que estreche el alcance; y lo que lo
acota en el peor caso es el TTL de ≤10 minutos.

La firma va **después** de escribir en Valkey: un alcance sin token es basura que
caduca sola, mientras que un token sin alcance es una credencial que falla en la
cara del usuario.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Sequence, Tuple
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.access_control import (
    Grant,
    ScopeSubject,
    TimeWindow,
    accessible_refs,
)
from app.services.scope_store import (
    RevocationIndexNotConfigured,
    ScopePurpose,
    ScopeStore,
    ScopeStoreUnavailable,
)
from app.utils.data_token import DataTokenIssuer, IssuedDataToken, compute_expiry

logger = logging.getLogger(__name__)


def next_scope_boundary(db: Session, subject: ScopeSubject) -> Optional[datetime]:
    """
    Instante en que la respuesta del resolver deja de ser cierta, o None.

    Punto de extensión para `team.visibility_rules`, cuyas ventanas horarias
    (`schedule`, JSONB) hacen que el alcance caduque solo con el paso del reloj.
    Hoy devuelve None —ningún cliente consume teams todavía— y el token usa el
    TTL máximo. Cuando teams entre, esta función es lo único que hay que
    implementar: el TTL adaptativo ya está cableado en `compute_expiry`.
    """
    return None


def issue_for_subject(
    db: Session,
    *,
    subject: ScopeSubject,
    subject_id: UUID,
    issuer: DataTokenIssuer,
    store: ScopeStore,
    now: Optional[datetime] = None,
) -> IssuedDataToken:
    """
    Emite un data token para `subject`.

    `subject_id` identifica a quién pertenece la credencial de cara al índice de
    revocación, y es independiente del sujeto cuyo alcance se calcula: en una
    sesión de soporte el operador es el dueño del token pero el alcance es el del
    cliente observado. Por eso son dos parámetros y no uno.
    """
    moment = now or datetime.now(timezone.utc)

    refs = accessible_refs(db, subject)
    expires_at = compute_expiry(
        moment, next_scope_boundary=next_scope_boundary(db, subject)
    )

    # El `jti` se genera aquí, antes de escribir y de firmar, para que el rastro
    # forense y el token lleven exactamente el mismo identificador.
    jti = uuid4()
    scope_ref = uuid4()
    ttl_seconds = int((expires_at - moment).total_seconds())
    store.write_scope(
        scope_ref,
        subject_id=subject_id,
        devices=refs.devices,
        units=refs.units,
        token_ttl_seconds=ttl_seconds,
        jti=jti,
    )

    return issuer.issue(scope_ref, expires_at=expires_at, issued_at=moment, jti=jti)


def issue_share_token(
    *,
    unit_ref: UUID,
    unit_id: UUID,
    device_ref: UUID,
    device_id: str,
    issuer: DataTokenIssuer,
    store: ScopeStore,
    ttl_seconds: Optional[int] = None,
    now: Optional[datetime] = None,
) -> IssuedDataToken:
    """
    Emite el token de un enlace de compartir ubicación.

    Mismo mecanismo que el data token de sesión, con un alcance de un solo
    dispositivo. Eso le regala al producto algo que hoy no tiene: **dejar de
    compartir**. Con el token v4.local anterior, un enlace emitido era válido sus
    treinta minutos y no había forma de apagarlo.

    El dueño a efectos de revocación es la **unidad**, no quien generó el enlace.
    Así "dejar de compartir esta unidad" apaga sus enlaces sin tocar los de otra
    unidad de la misma persona, que es la acción que existe en el producto.
    """
    moment = now or datetime.now(timezone.utc)
    ttl = ttl_seconds if ttl_seconds is not None else settings.SHARE_TOKEN_TTL_SECONDS
    expires_at = moment + timedelta(seconds=ttl)

    jti = uuid4()
    scope_ref = uuid4()
    # Ventana abierta: un enlace compartido es sobre dónde está el vehículo
    # ahora, no sobre su histórico. Que sea abierta es además lo único que
    # autoriza los datos en vivo, que es justo lo que el enlace sirve.
    ahora = (TimeWindow(),)
    store.write_scope(
        scope_ref,
        subject_id=unit_id,
        devices={device_ref: Grant(internal_id=device_id, windows=ahora)},
        units={unit_ref: Grant(internal_id=str(unit_id), windows=ahora)},
        token_ttl_seconds=ttl,
        jti=jti,
        purpose=ScopePurpose.SHARE,
    )

    return issuer.issue(scope_ref, expires_at=expires_at, issued_at=moment, jti=jti)


def gac_owner_id(operator: str) -> UUID:
    """
    Dueño, en el índice de revocación, de los tokens de un operador de GAC.

    El `internal_id` de GAC no es un UUID de este servicio; se deriva uno estable
    para que todas las emisiones de un operador compartan índice.
    """
    return uuid5(NAMESPACE_URL, f"gac:{operator}")


def issue_gac_token(
    *,
    devices: Sequence[Tuple[UUID, str]],
    operator: str,
    issuer: DataTokenIssuer,
    store: ScopeStore,
    now: Optional[datetime] = None,
) -> IssuedDataToken:
    """
    Emite el token con el que GAC lee del plano de datos los dispositivos que
    pide, como pares `(device_ref, device_id)`.

    GAC administra el inventario entero: no hay alcance que resolver, sólo los
    dispositivos de la petición. La ventana es completa —histórico y en vivo—
    porque es lo que su mapa ya muestra hoy. Lo que sí se acota es el número de
    dispositivos (lo valida el endpoint) y la vida del token, la misma que la de
    una sesión de Nexus.
    """
    moment = now or datetime.now(timezone.utc)
    expires_at = compute_expiry(moment)

    jti = uuid4()
    scope_ref = uuid4()
    siempre = (TimeWindow(),)
    store.write_scope(
        scope_ref,
        subject_id=gac_owner_id(operator),
        devices={
            ref: Grant(internal_id=device_id, windows=siempre)
            for ref, device_id in devices
        },
        units={},
        token_ttl_seconds=int((expires_at - moment).total_seconds()),
        jti=jti,
        purpose=ScopePurpose.GAC,
    )

    return issuer.issue(scope_ref, expires_at=expires_at, issued_at=moment, jti=jti)


def revoke_shares_for_unit(store: ScopeStore, unit_id: UUID) -> int:
    """Apaga los enlaces compartidos de una unidad. Devuelve cuántos había."""
    return len(store.revoke_all_for_subject(unit_id, ScopePurpose.SHARE))


def best_effort_revoke(
    store: ScopeStore, subject_id: UUID, purpose: ScopePurpose
) -> int:
    """
    Revoca sin dejar que un fallo del store tumbe la operación que la provocó.

    La autoridad sobre los permisos es Postgres: desasignar una unidad ya ha
    surtido efecto cuando llegamos aquí. Revocar solo adelanta el momento en que
    el plano de datos se entera, de días a segundos. Si Valkey no responde, el
    peor caso es que el alcance viejo siga vivo hasta que caduque —diez minutos—,
    y eso no justifica devolverle un error al usuario por una operación que ya se
    completó correctamente.

    Distinto es "dejar de compartir", que es una acción cuyo único efecto ES la
    revocación: ahí el fallo tiene que verse, y por eso ese camino no pasa por
    aquí.
    """
    try:
        return len(store.revoke_all_for_subject(subject_id, purpose))
    except (ScopeStoreUnavailable, RevocationIndexNotConfigured) as exc:
        logger.warning(
            "No se pudieron revocar los alcances de %s (%s): %s",
            purpose.value,
            subject_id,
            exc,
        )
        return 0


def revoke_sessions_for_user(store: ScopeStore, user_id: UUID) -> int:
    """Invalida los data tokens de sesión de un usuario. Best effort."""
    return best_effort_revoke(store, user_id, ScopePurpose.SESSION)


def revoke_shares_for_unit_best_effort(store: ScopeStore, unit_id: UUID) -> int:
    """Apaga los enlaces compartidos de una unidad sin propagar fallos."""
    return best_effort_revoke(store, unit_id, ScopePurpose.SHARE)
