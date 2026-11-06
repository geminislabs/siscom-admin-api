"""Revocación de data tokens de sesión, disparada por el ORM y no por cada endpoint.

POR QUÉ AQUÍ
============
Emitir ya no revoca (D1 del plan de data token y versiones): los tokens viven
≤10 minutos y dos emisiones seguidas del mismo usuario —una pestaña y el
móvil, o dos refresh que se cruzan— no deben matarse entre sí. A cambio, todo
lo que **estrecha** el alcance de alguien tiene que revocar sus tokens vivos.

La auditoría del 06/11/2026 encontró que sólo cuatro de los catorce caminos que
estrechan permisos lo hacían, cada uno con su llamada a mano. Por eso esto
sigue el mismo patrón que `app/services/messaging/control_plane.py`: se engancha
a toda sesión del ORM y mira las tablas de las que sale el alcance
(`access_control.accessible_refs`), venga la escritura del endpoint que venga,
incluidos los internos que usa GAC.

QUÉ ESTRECHA
============
- `users.status` deja de ser `ACTIVE` → ese usuario.
- Una membresía se borra, deja de ser `ACTIVE` o deja de ser `owner` → ese
  usuario (un owner ve toda la organización; un member, sólo sus unidades).
- Una concesión de `user_units` se borra o cambia de dueño → ese usuario.
- Un dispositivo sale de una unidad (`unit_devices.unassigned_at` pasa a tener
  valor, o la fila se borra o cambia de unidad) → quien veía esa unidad.
- Una unidad se borra (lógicamente) o cambia de organización → quien la veía.

"Quien veía la unidad" son sus concesiones en `user_units` más los owners
activos de su organización (la de antes, si se movió).

Lo que **ensancha** no revoca a propósito: el token viejo no da nada de más, y
revocarlo sólo obligaría al cliente a pedir otro.

Lo único que se salta esto es escribir sin el ORM; el mismo límite que el plano
de control, que `tests/test_control_plane_sin_escrituras_masivas.py` vigila.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional
from uuid import UUID

from sqlalchemy import event, inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_USUARIOS = "revocacion_usuarios"
_UNIDADES = "revocacion_unidades"
_ORGANIZACIONES = "revocacion_organizaciones"

_fabrica_de_store: Optional[Callable[[], Any]] = None


def usar_store(fabrica: Optional[Callable[[], Any]]) -> None:
    """Cambia de dónde sale el store. Los tests lo usan para no hablar con Valkey."""
    global _fabrica_de_store
    _fabrica_de_store = fabrica


def _obtener_store() -> Any:
    if _fabrica_de_store is not None:
        return _fabrica_de_store()
    # El mismo singleton que inyectan los endpoints: reutiliza el pool.
    from app.api.deps import get_scope_store

    return get_scope_store()


# ---------------------------------------------------------------------------
# 1. Qué estrechó el flush
# ---------------------------------------------------------------------------


def _valor(v: Any) -> Any:
    return getattr(v, "value", v)


# El valor anterior no se conoce cuando el atributo estaba expirado (p. ej. tras
# un commit) al asignarlo: SQLAlchemy no lo carga para compararlo. Se trata
# como si estrechara: revocar de más es inofensivo, de menos no.
_DESCONOCIDO = object()


def _anterior(obj: Any, atributo: str) -> tuple[bool, Any]:
    """`(cambió, valor anterior)` del atributo en este flush."""
    historia = inspect(obj).attrs[atributo].history
    if not historia.has_changes():
        return False, _valor(getattr(obj, atributo))
    if historia.deleted:
        return True, _valor(historia.deleted[0])
    return True, _DESCONOCIDO


def _clave_anterior(obj: Any, atributo: str) -> Any:
    """La clave de antes del flush si se conoce; si no, la actual."""
    _, previo = _anterior(obj, atributo)
    return _valor(getattr(obj, atributo)) if previo is _DESCONOCIDO else previo


def _anotar(session: Session, _flush_context: Any) -> None:
    from app.models.organization_user import (
        MembershipStatus,
        OrganizationRole,
        OrganizationUser,
    )
    from app.models.unit import Unit
    from app.models.unit_device import UnitDevice
    from app.models.user import User, UserStatus
    from app.models.user_unit import UserUnit

    usuarios: set[UUID] = session.info.setdefault(_USUARIOS, set())
    unidades: set[UUID] = session.info.setdefault(_UNIDADES, set())
    organizaciones: set[UUID] = session.info.setdefault(_ORGANIZACIONES, set())

    era_owner = (OrganizationRole.OWNER.value, _DESCONOCIDO)
    era_activa = (MembershipStatus.ACTIVE.value, _DESCONOCIDO)
    estaba_abierto = (None, _DESCONOCIDO)

    for obj in session.deleted:
        if isinstance(obj, (OrganizationUser, UserUnit)):
            usuarios.add(_clave_anterior(obj, "user_id"))
        elif isinstance(obj, UnitDevice):
            unidades.add(_clave_anterior(obj, "unit_id"))

    for obj in session.dirty:
        if isinstance(obj, User):
            cambio, _ = _anterior(obj, "status")
            if cambio and _valor(obj.status) != UserStatus.ACTIVE.value:
                usuarios.add(obj.id)
        elif isinstance(obj, OrganizationUser):
            cambio_rol, rol = _anterior(obj, "role")
            cambio_estado, estado = _anterior(obj, "status")
            cambio_clave = (
                _anterior(obj, "user_id")[0] or _anterior(obj, "organization_id")[0]
            )
            if (
                (cambio_rol and rol in era_owner)
                or (cambio_estado and estado in era_activa)
                or cambio_clave
            ):
                usuarios.add(_clave_anterior(obj, "user_id"))
        elif isinstance(obj, UserUnit):
            # Quitarle a una concesión el histórico también estrecha.
            cambio_hist, hist = _anterior(obj, "include_history")
            pierde_historia = cambio_hist and hist in (True, _DESCONOCIDO)
            if (
                _anterior(obj, "user_id")[0]
                or _anterior(obj, "unit_id")[0]
                or pierde_historia
            ):
                usuarios.add(_clave_anterior(obj, "user_id"))
        elif isinstance(obj, UnitDevice):
            cambio_fin, fin = _anterior(obj, "unassigned_at")
            cierra = (
                cambio_fin and fin in estaba_abierto and obj.unassigned_at is not None
            )
            if cierra or _anterior(obj, "unit_id")[0]:
                unidades.add(_clave_anterior(obj, "unit_id"))
        elif isinstance(obj, Unit):
            cambio_borrado, borrado = _anterior(obj, "deleted_at")
            borra = (
                cambio_borrado
                and borrado in estaba_abierto
                and obj.deleted_at is not None
            )
            cambio_org, org = _anterior(obj, "organization_id")
            if borra or cambio_org:
                unidades.add(obj.id)
                if cambio_org and org not in (None, _DESCONOCIDO):
                    organizaciones.add(org)


def _descartar(session: Session, *_args: Any) -> None:
    # Mismo criterio que el plano de control: si sólo se revirtió un SAVEPOINT,
    # lo anotado antes puede confirmarse todavía. Revocar de más es inofensivo.
    if session.in_transaction():
        return
    for clave in (_USUARIOS, _UNIDADES, _ORGANIZACIONES):
        session.info.pop(clave, None)


# ---------------------------------------------------------------------------
# 2. Quién veía las unidades afectadas
# ---------------------------------------------------------------------------


def usuarios_que_ven(
    conn: Any, unidades: set[UUID], organizaciones: set[UUID]
) -> set[UUID]:
    """Concesiones de esas unidades más los owners activos de sus organizaciones."""
    if not unidades and not organizaciones:
        return set()

    usuarios: set[UUID] = set()
    orgs = set(organizaciones)
    for unidad in unidades:
        for (user_id,) in conn.execute(
            text("SELECT user_id FROM public.user_units WHERE unit_id = :u"),
            {"u": unidad},
        ):
            usuarios.add(user_id)
        for (org_id,) in conn.execute(
            text("SELECT organization_id FROM public.units WHERE id = :u"),
            {"u": unidad},
        ):
            if org_id is not None:
                orgs.add(org_id)

    for org in orgs:
        for (user_id,) in conn.execute(
            text(
                "SELECT user_id FROM public.organization_users"
                " WHERE organization_id = :o AND role = 'owner' AND status = 'ACTIVE'"
            ),
            {"o": org},
        ):
            usuarios.add(user_id)
    return usuarios


# ---------------------------------------------------------------------------
# 3. Revocar tras el commit
# ---------------------------------------------------------------------------


def _revocar_lo_anotado(session: Session) -> None:
    usuarios = session.info.pop(_USUARIOS, None) or set()
    unidades = session.info.pop(_UNIDADES, None) or set()
    organizaciones = session.info.pop(_ORGANIZACIONES, None) or set()
    if not usuarios and not unidades and not organizaciones:
        return

    from app.services.data_token_issuance import revoke_sessions_for_user

    try:
        if unidades or organizaciones:
            # Como en el plano de control: la sesión ya no tiene transacción, se
            # lee con una conexión aparte sobre el mismo bind.
            bind = session.get_bind()
            if hasattr(bind, "connect"):
                with bind.connect() as conn:
                    usuarios |= usuarios_que_ven(conn, unidades, organizaciones)
            else:
                usuarios |= usuarios_que_ven(bind, unidades, organizaciones)
        store = _obtener_store()
    except Exception:
        # El cambio de permisos ya está confirmado en Postgres. Si no se puede
        # revocar, el peor caso es que el token viejo viva hasta su caducidad.
        logger.exception(
            "session_revocation_failed",
            extra={"extra_data": {"units": sorted(str(u) for u in unidades)}},
        )
        return

    for user_id in usuarios:
        if user_id is not None:
            revoke_sessions_for_user(store, user_id)


# ---------------------------------------------------------------------------
# Registro
# ---------------------------------------------------------------------------


def registrar() -> None:
    """Engancha los tres momentos a toda sesión del ORM. Idempotente."""
    for nombre, funcion in (
        ("after_flush", _anotar),
        ("after_commit", _revocar_lo_anotado),
        ("after_rollback", _descartar),
    ):
        if not event.contains(Session, nombre, funcion):
            event.listen(Session, nombre, funcion)
