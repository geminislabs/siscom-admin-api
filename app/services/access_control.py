"""
Resolución de qué unidades y dispositivos puede ver un sujeto.

SUJETO EXPLÍCITO
================
Estas funciones no deducen de quién es el alcance: se lo dicen. Un `ScopeSubject`
nombra exactamente para quién se calcula la visibilidad, y el llamante decide qué
sujeto corresponde.

Esa separación importa. El caso de una sesión de soporte —un operador de
plataforma que necesita ver los datos de un cliente concreto, con motivo y
caducidad corta— se resuelve pasando *otro sujeto*, no añadiendo una rama dentro
del resolver. Modo normal y modo soporte comparten función, no comparten
condicional: un fallo en el segundo no puede ensanchar el primero.

La traducción de "usuario autenticado" a "sujeto" vive en `subject_for_user`, que
es donde se aplica la política (hoy, el `is_master` heredado).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.device import Device
from app.models.unit import Unit
from app.models.unit_device import UnitDevice
from app.models.user import User
from app.models.user_unit import UserUnit


def es_miembro(organization_id: UUID, solo_activos: bool = True):
    """Condición SQL: `User.id` tiene membresía en `organization_id`.

    Es la única definición de «pertenecer a una organización». La autoridad es
    `organization_users`; `users.default_organization_id` es solo la
    organización con la que nació el usuario (y con la que abre sesión si no
    pide otra), y no dice a qué organizaciones pertenece. Filtrar por ella
    dejaba fuera a quien llegó desde otra organización: no aparecía en la
    lista de usuarios y no se le podían conceder unidades.

    `tests/test_pertenencia_por_membresia.py` falla si un endpoint vuelve a
    decidir pertenencia comparando `default_organization_id`.
    """
    from app.models.organization_user import MembershipStatus, OrganizationUser

    miembros = select(OrganizationUser.user_id).where(
        OrganizationUser.organization_id == organization_id
    )
    if solo_activos:
        miembros = miembros.where(
            OrganizationUser.status == MembershipStatus.ACTIVE.value
        )
    return User.id.in_(miembros)


@dataclass(frozen=True)
class ScopeSubject:
    """
    Para quién se calcula la visibilidad.

    - `user_id is None` → sujeto de organización: todas las unidades activas de
      `organization_id`.
    - `user_id` presente → sujeto de usuario: solo las unidades concedidas en
      `user_units`, siempre dentro de `organization_id`.

    Es inmutable a propósito: una vez decidido el sujeto, nada aguas abajo puede
    ensancharlo.
    """

    organization_id: UUID
    user_id: Optional[UUID] = None

    @property
    def is_organization_wide(self) -> bool:
        return self.user_id is None


def subject_for_user(user: User) -> ScopeSubject:
    """
    Traduce un usuario autenticado al sujeto cuya visibilidad le corresponde.

    Ve toda la organización en la que actúa la sesión quien es su `owner` con
    membresía activa (`User.is_owner_of`); los demás, solo sus `user_units`. Es
    la misma regla que aplica alert-distributor a push y WebSocket (ADR-008 §6).

    Antes era `users.is_master`, que es del usuario y no de la membresía: con el
    selector de cuenta, un maestro que actuaba en otra organización donde solo
    es `member` veía todas sus unidades. Para quien actúa en su organización por
    defecto no cambia nada: `owner` ≡ maestro, verificado en producción el
    19/10/2026.
    """
    if user.is_active_organization_owner:
        return ScopeSubject(organization_id=user.organization_id)
    return ScopeSubject(organization_id=user.organization_id, user_id=user.id)


def accessible_unit_ids(db: Session, subject: ScopeSubject) -> List[UUID]:
    """IDs de unidades visibles para el sujeto. Excluye unidades borradas."""
    query = db.query(Unit.id).filter(
        Unit.organization_id == subject.organization_id,
        Unit.deleted_at.is_(None),
    )

    if not subject.is_organization_wide:
        query = query.join(UserUnit, UserUnit.unit_id == Unit.id).filter(
            UserUnit.user_id == subject.user_id
        )

    return [row[0] for row in query.all()]


@dataclass(frozen=True)
class TimeWindow:
    """
    Intervalo durante el cual un sujeto pudo ver algo. `[start, end)`.

    `start = None` → sin límite inferior conocido.
    `end = None`   → **abierto**: sigue vigente ahora. Es la única forma en que se
    autorizan los datos en vivo (posición actual, WebSocket); no hay una regla
    aparte para "en vivo", es el mismo predicado evaluado en el instante actual.
    """

    start: Optional[datetime] = None
    end: Optional[datetime] = None

    @property
    def is_open(self) -> bool:
        return self.end is None

    def overlaps(self, frm: Optional[datetime], to: Optional[datetime]):
        """Intersección con `[frm, to)`, o None si no se solapan."""
        lo = max((x for x in (self.start, frm) if x is not None), default=None)
        hi = min((x for x in (self.end, to) if x is not None), default=None)
        if lo is not None and hi is not None and lo >= hi:
            return None
        return (lo, hi)


def _aware(moment: Optional[datetime]) -> Optional[datetime]:
    """
    Normaliza a UTC consciente de zona.

    PostgreSQL devuelve `TIMESTAMP WITH TIME ZONE`, pero cualquier fila escrita
    antes de que la columna llevara zona devuelve una fecha ingenua. Comparar
    unas con otras lanza `TypeError`, así que normalizar en la frontera evita
    que el fallo aparezca solo con datos reales.
    """
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _merge(windows: List[TimeWindow]) -> List[TimeWindow]:
    """
    Normaliza a intervalos disjuntos y ordenados.

    El esquema no impide que un dispositivo tenga asignaciones solapadas, y dos
    ventanas contiguas describen el mismo permiso que una sola. Normalizar aquí
    evita que cada consumidor tenga que hacerlo.
    """
    if not windows:
        return []

    _MIN = datetime.min.replace(tzinfo=timezone.utc)
    ordered = sorted(windows, key=lambda w: w.start or _MIN)

    merged = [ordered[0]]
    for w in ordered[1:]:
        last = merged[-1]
        if last.is_open:
            # Una ventana abierta absorbe todo lo posterior
            continue
        if w.start is None or w.start <= last.end:
            merged[-1] = TimeWindow(
                start=last.start,
                end=None if w.is_open else max(last.end, w.end),
            )
        else:
            merged.append(w)
    return merged


@dataclass(frozen=True)
class Grant:
    """
    Qué identificador interno hay detrás de una referencia opaca, y **cuándo**.

    La ventana viaja con la referencia porque el plano de datos no puede
    deducirla: hacerlo exigiría conocer el modelo de unidades y asignaciones,
    que es justo lo que no debe aprender.
    """

    internal_id: str
    windows: Tuple[TimeWindow, ...] = ()

    @property
    def is_live(self) -> bool:
        """Hay ventana abierta: se autorizan también los datos en vivo."""
        return any(w.is_open for w in self.windows)

    def clip(self, frm: Optional[datetime], to: Optional[datetime]) -> List[tuple]:
        """
        Recorta `[frm, to)` a lo que el sujeto pudo ver. Lista vacía = nada.

        Se recorta, no se rechaza: pedir enero–diciembre habiendo tenido el
        equipo enero–marzo devuelve enero–marzo. Aquí no hay oráculo de
        pertenencia que proteger —el sujeto ya conoce los límites de su propia
        ventana—, al contrario que con una referencia ajena, que sí se rechaza
        entera.
        """
        return [r for w in self.windows if (r := w.overlaps(frm, to)) is not None]

    def to_wire(self) -> dict:
        """Forma que se materializa en Valkey y que lee el plano de datos."""
        return {
            "id": self.internal_id,
            "windows": [
                {
                    "from": w.start.isoformat() if w.start else None,
                    "to": w.end.isoformat() if w.end else None,
                }
                for w in self.windows
            ],
        }


@dataclass(frozen=True)
class AccessibleRefs:
    """Alcance del sujeto: referencia opaca → concesión con su ventana."""

    units: Dict[UUID, Grant]
    devices: Dict[UUID, Grant]


def accessible_refs(db: Session, subject: ScopeSubject) -> AccessibleRefs:
    """
    Alcance del sujeto, indexado por identificador **opaco** y con ventana.

    La pregunta que responde no es "¿puede ver el dispositivo X?" —un booleano
    derivado del estado actual, incapaz de decir nada del pasado— sino "¿puede
    ver el dispositivo X **entre t1 y t2**?". El historial de `unit_devices` ya
    contiene la respuesta; antes se descartaba filtrando por asignación activa.

    Son **varios** intervalos por dispositivo, no uno: un equipo puede estar en
    una flota, irse a otra y volver, y un modelo de intervalo único falla justo
    en ese caso.

    LÍMITE DEL ESQUEMA: `unit_devices` tiene `UNIQUE(unit_id, device_id)`, así que
    un dispositivo no puede reasignarse **a la misma unidad** dos veces. El caso
    del equipo que se va y vuelve solo produce dos ventanas si vuelve a una unidad
    distinta de la organización; volver a la misma no es representable sin
    levantar esa restricción.

    LÍMITE CONOCIDO: la ventana sale de la relación unidad↔dispositivo, que es de
    la organización. La relación usuario↔unidad no tiene historial —`user_units`
    guarda `granted_at` pero el revocado es un borrado físico—, así que un usuario
    al que se le concede una unidad hoy ve el histórico del dispositivo en esa
    unidad desde antes de tener acceso. Acotar eso exigiría historial de
    concesiones, que no existe hoy.

    Que el `device_id` (el IMEI) figure como valor no contradice la migración de
    referencias: siscom-api ya tiene todos los IMEIs, sus tablas están indexadas
    por ellos. La referencia existe para que el IMEI no llegue al navegador ni a
    las URLs.
    """
    unit_ids = accessible_unit_ids(db, subject)
    if not unit_ids:
        return AccessibleRefs(units={}, devices={})

    # Las unidades son de la organización de forma permanente: su ventana está
    # abierta mientras la unidad no esté borrada, y las borradas ya se han
    # excluido en `accessible_unit_ids`.
    units = {
        row.unit_ref: Grant(internal_id=str(row.id), windows=(TimeWindow(),))
        for row in db.query(Unit.unit_ref, Unit.id).filter(Unit.id.in_(unit_ids)).all()
    }

    rows = (
        db.query(
            Device.device_ref,
            Device.device_id,
            UnitDevice.assigned_at,
            UnitDevice.unassigned_at,
        )
        .join(UnitDevice, UnitDevice.device_id == Device.device_id)
        .filter(UnitDevice.unit_id.in_(unit_ids))
        .all()
    )

    por_ref: Dict[UUID, List[TimeWindow]] = defaultdict(list)
    id_por_ref: Dict[UUID, str] = {}
    for row in rows:
        por_ref[row.device_ref].append(
            TimeWindow(start=_aware(row.assigned_at), end=_aware(row.unassigned_at))
        )
        id_por_ref[row.device_ref] = row.device_id

    devices = {
        ref: Grant(internal_id=id_por_ref[ref], windows=tuple(_merge(windows)))
        for ref, windows in por_ref.items()
    }

    return AccessibleRefs(units=units, devices=devices)


def get_accessible_unit_ids(db: Session, user: User) -> List[UUID]:
    """
    Atajo para el caso habitual: la visibilidad del propio usuario autenticado.

    Equivale a `accessible_unit_ids(db, subject_for_user(user))`.
    """
    return accessible_unit_ids(db, subject_for_user(user))
