"""Eventos de `control-plane-events`, emitidos por el ORM y no por cada endpoint.

El contrato está en `docs/architecture/eventos-de-control.md` y la decisión en
el ADR-008. Lo que hace este módulo, en tres momentos de cada transacción:

1. `after_flush`: anota qué claves de qué entidades tocó el flush. No importa
   qué endpoint, servicio o script escribió: si pasó por una sesión del ORM,
   queda anotado.
2. `after_commit`: lee la fila de cada clave **desde su vista**
   `control_plane.*` —la misma que usan los consumidores como foto de
   arranque— y la publica. Si la fila existe, `UPSERT`; si no, `DELETE`. Así
   el evento y la foto no pueden divergir.
3. `after_rollback`: descarta lo anotado.

Se publica después del commit y no antes a propósito (ADR-008 §5): un evento
que falta deja a un consumidor desactualizado hasta su siguiente arranque; uno
que sobra le concede algo que nunca existió. El outbox, cuando llegue, mueve el
paso 2 a `before_commit` e inserta en vez de publicar.

Lo único que se salta esto es escribir sin el ORM: `query(...).update()`,
`query(...).delete()` o SQL crudo sobre estas tablas.
`tests/test_control_plane_sin_escrituras_masivas.py` falla si aparece alguno.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Iterable, Optional
from uuid import UUID

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.messaging.control_events import build_control_event, to_utc_iso_z

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
ESQUEMA = "control_plane"

_CLAVES = "control_plane_claves"
_UNIDADES = "control_plane_unidades"


@dataclass(frozen=True)
class Entidad:
    """Una entidad del contrato: su vista, sus columnas (= su `data`) y su clave."""

    vista: str
    columnas: tuple[str, ...]
    clave: tuple[str, ...]


# Las columnas son el `data` de cada evento, en orden. Coinciden con las vistas
# de la migración 044; `tests/test_vistas_del_plano_de_control_esquema.py` lo
# comprueba contra la base migrada.
ENTIDADES: dict[str, Entidad] = {
    "user": Entidad("users", ("id", "status"), ("id",)),
    "organization_user": Entidad(
        "organization_users",
        ("organization_id", "user_id", "role", "status"),
        ("organization_id", "user_id"),
    ),
    "user_unit": Entidad(
        "user_units",
        ("organization_id", "user_id", "unit_id", "role"),
        ("user_id", "unit_id"),
    ),
    "unit_device": Entidad(
        "unit_devices", ("device_id", "unit_id", "organization_id"), ("device_id",)
    ),
    "user_device": Entidad(
        "user_devices",
        (
            "id",
            "user_id",
            "device_token",
            "platform",
            "endpoint_arn",
            "is_active",
            "updated_at",
        ),
        ("id",),
    ),
}


def clave_kafka(entidad: str, valores: tuple) -> str:
    return ":".join([entidad, *(str(v) for v in valores)])


# ---------------------------------------------------------------------------
# 1. Qué tocó el flush
# ---------------------------------------------------------------------------


def _valores(obj: Any, atributos: Iterable[str]) -> list[tuple]:
    """El valor actual de la clave y, si cambió en este flush, también el anterior.

    Si una membresía cambia de usuario o una asignación de equipo, la clave vieja
    deja de existir y su consumidor tiene que recibir el DELETE.
    """
    estado = inspect(obj)
    actual = tuple(getattr(obj, a) for a in atributos)
    resultado = [actual]

    anterior = []
    cambio = False
    for a in atributos:
        historia = estado.attrs[a].history
        if historia.deleted:
            anterior.append(historia.deleted[0])
            cambio = True
        else:
            anterior.append(getattr(obj, a))
    if cambio:
        resultado.append(tuple(anterior))
    return resultado


def _cambio(obj: Any, atributo: str) -> bool:
    return inspect(obj).attrs[atributo].history.has_changes()


def _anotar(session: Session, _flush_context: Any) -> None:
    # Imports diferidos: los modelos importan medio `app`, y este módulo lo
    # importa `app/main.py` al arrancar.
    from app.models.organization_user import OrganizationUser
    from app.models.unit import Unit
    from app.models.unit_device import UnitDevice
    from app.models.user import User
    from app.models.user_device import UserDevice
    from app.models.user_unit import UserUnit

    claves: set[tuple[str, tuple]] = session.info.setdefault(_CLAVES, set())
    unidades: set[UUID] = session.info.setdefault(_UNIDADES, set())

    # Por identidad: los modelos de SQLModel no son hashables.
    nuevos = {id(o) for o in session.new}
    for obj in (*session.new, *session.dirty, *session.deleted):
        if isinstance(obj, OrganizationUser):
            for v in _valores(obj, ("organization_id", "user_id")):
                claves.add(("organization_user", v))
        elif isinstance(obj, User):
            # Un usuario cambia de muchas cosas (último acceso, nombre…); sólo
            # su alta y su `status` le importan al contrato.
            if id(obj) in nuevos or _cambio(obj, "status"):
                claves.add(("user", (obj.id,)))
        elif isinstance(obj, UserUnit):
            for v in _valores(obj, ("user_id", "unit_id")):
                claves.add(("user_unit", v))
        elif isinstance(obj, UnitDevice):
            for v in _valores(obj, ("device_id",)):
                claves.add(("unit_device", v))
        elif isinstance(obj, UserDevice):
            claves.add(("user_device", (obj.id,)))
        elif isinstance(obj, Unit) and id(obj) not in nuevos:
            # Borrar una unidad (lógicamente) o moverla de organización cambia
            # lo que dicen las vistas de sus concesiones y de su equipo, aunque
            # esas filas no se toquen. Se resuelven al publicar.
            if _cambio(obj, "deleted_at") or _cambio(obj, "organization_id"):
                unidades.add(obj.id)


def _descartar(session: Session, *_args: Any) -> None:
    # Sólo cuando ya no queda transacción. Si lo que se revirtió fue un
    # SAVEPOINT, la transacción de fuera sigue y lo anotado antes puede
    # confirmarse todavía. Conservar una clave de más es inofensivo —su evento
    # dice el estado actual, sea cual sea—; perder una no.
    if session.in_transaction():
        return
    session.info.pop(_CLAVES, None)
    session.info.pop(_UNIDADES, None)


# ---------------------------------------------------------------------------
# 2. Construir los eventos desde las vistas
# ---------------------------------------------------------------------------


def _json(valor: Any) -> Any:
    if isinstance(valor, UUID):
        return str(valor)
    if isinstance(valor, datetime):
        return to_utc_iso_z(valor)
    return valor


def _expandir_unidades(conn: Any, unidades: set[UUID]) -> set[tuple[str, tuple]]:
    """Las claves de concesiones y equipos de unidades borradas o movidas."""
    claves: set[tuple[str, tuple]] = set()
    for unidad in unidades:
        for user_id, unit_id in conn.execute(
            text("SELECT user_id, unit_id FROM public.user_units WHERE unit_id = :u"),
            {"u": unidad},
        ):
            claves.add(("user_unit", (user_id, unit_id)))
        for (device_id,) in conn.execute(
            text("SELECT device_id FROM public.unit_devices WHERE unit_id = :u"),
            {"u": unidad},
        ):
            claves.add(("unit_device", (device_id,)))
    return claves


def construir_eventos(
    conn: Any, claves: set[tuple[str, tuple]], unidades: set[UUID] = frozenset()
) -> list[tuple[str, dict[str, Any]]]:
    """Lee el estado actual de cada clave y devuelve `(key, evento)` en orden estable."""
    todas = set(claves) | _expandir_unidades(conn, set(unidades))

    eventos = []
    for entidad, valores in sorted(todas, key=lambda c: (c[0], [str(v) for v in c[1]])):
        if any(v is None for v in valores):
            continue
        definicion = ENTIDADES[entidad]
        condicion = " AND ".join(f"{c} = :{c}" for c in definicion.clave)
        fila = (
            conn.execute(
                text(
                    f"SELECT {', '.join(definicion.columnas)} "
                    f"FROM {ESQUEMA}.{definicion.vista} WHERE {condicion}"
                ),
                dict(zip(definicion.clave, valores, strict=True)),
            )
            .mappings()
            .first()
        )

        if fila is None:
            event_type = "DELETE"
            data = {c: _json(v) for c, v in zip(definicion.clave, valores, strict=True)}
        else:
            event_type = "UPSERT"
            data = {c: _json(fila[c]) for c in definicion.columnas}

        evento = build_control_event(
            event_type=event_type,
            entity=entidad,
            organization_id=data.get("organization_id"),
            data=data,
        )
        evento["schema_version"] = SCHEMA_VERSION
        eventos.append((clave_kafka(entidad, valores), evento))
    return eventos


# ---------------------------------------------------------------------------
# 3. Publicar
# ---------------------------------------------------------------------------


_productor: Optional[Any] = None
_fabrica_de_productor: Optional[Callable[[], Any]] = None


def usar_productor(fabrica: Optional[Callable[[], Any]]) -> None:
    """Cambia de dónde sale el productor. Los tests lo usan para no hablar con Kafka."""
    global _productor, _fabrica_de_productor
    _fabrica_de_productor = fabrica
    _productor = None


def _obtener_productor() -> Any:
    global _productor
    if _productor is None:
        if _fabrica_de_productor is not None:
            _productor = _fabrica_de_productor()
        else:
            from app.services.messaging.kafka_producer import (
                ControlPlaneKafkaProducer,
            )

            _productor = ControlPlaneKafkaProducer()
    return _productor


def cerrar() -> None:
    """Cierra el productor al apagar la API."""
    global _productor
    if _productor is not None and hasattr(_productor, "close"):
        _productor.close()
    _productor = None


def publicar(eventos: list[tuple[str, dict[str, Any]]]) -> None:
    """Publica cada evento con reintentos. Nunca lanza: el commit ya ocurrió.

    Un evento que no sale tras los reintentos deja `control_event_publish_failed`
    en el log con su entidad y su key, que es lo que mide si hace falta el
    outbox (ADR-008 §5).
    """
    if not eventos:
        return
    productor = _obtener_productor()
    # Sin brokers o sin cliente de Kafka no hay nada transitorio que reintentar:
    # es configuración, y reintentar sólo retrasaría cada respuesta.
    intentos = (
        max(1, settings.CONTROL_PLANE_PUBLISH_ATTEMPTS)
        if getattr(productor, "configurado", True)
        else 1
    )

    for key, evento in eventos:
        publicado = False
        for intento in range(intentos):
            try:
                publicado = productor.publish_update(payload=evento, key=key)
            except Exception:
                logger.exception("Error publicando evento del plano de control")
                publicado = False
            if publicado:
                break
            if intento < intentos - 1:
                time.sleep(0.25 * (2**intento))

        if not publicado:
            logger.error(
                "control_event_publish_failed",
                extra={
                    "extra_data": {
                        "entity": evento["entity"],
                        "event_type": evento["event_type"],
                        "key": key,
                        "attempts": intentos,
                    }
                },
            )


def _publicar_lo_anotado(session: Session) -> None:
    claves = session.info.pop(_CLAVES, None) or set()
    unidades = session.info.pop(_UNIDADES, None) or set()
    if not claves and not unidades:
        return
    if not settings.KAFKA_CONTROL_PLANE_TOPIC:
        return

    # La sesión ya no tiene transacción y no puede ejecutar SQL aquí. Se lee con
    # una conexión aparte sobre el mismo bind: en producción es el engine y ve
    # lo confirmado; en los tests es la conexión con la transacción externa.
    try:
        bind = session.get_bind()
        if hasattr(bind, "connect"):
            with bind.connect() as conn:
                eventos = construir_eventos(conn, claves, unidades)
        else:
            eventos = construir_eventos(bind, claves, unidades)
    except Exception:
        logger.exception(
            "control_event_build_failed",
            extra={"extra_data": {"keys": sorted(str(c) for c in claves)}},
        )
        return

    publicar(eventos)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


def registrar() -> None:
    """Engancha los tres momentos a toda sesión del ORM. Idempotente."""
    for nombre, funcion in (
        ("after_flush", _anotar),
        ("after_commit", _publicar_lo_anotado),
        ("after_rollback", _descartar),
    ):
        if not event.contains(Session, nombre, funcion):
            event.listen(Session, nombre, funcion)
