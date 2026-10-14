"""La `043` deja auditar: `account_events.id` se genera en la base.

En producción la columna era `NOT NULL` sin DEFAULT y el modelo cuenta con
`gen_random_uuid()`, así que cada `AuditService.log_event` respondía 500. Va
como test de esquema porque el harness normal construye la tabla con
`create_all()`, desde el modelo que ya trae el default: ahí nunca falló.

Se escribe con el mismo `AuditService` que usan los endpoints, no con un INSERT
a mano, para que lo que se prueba sea el camino que caía.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from app.models.account_event import ActorType, EventType, TargetType
from app.services.audit import AuditService
from tests import esquema_desechable as desechable

BASE = "siscom_test_defaults_de_id"
REVISION_ANTERIOR = "042_marca_de_la_invitacion"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def _cuenta(engine):
    cuenta = uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO public.accounts (id, account_name) VALUES (:id, 'Cuenta')"
            ),
            {"id": cuenta},
        )
    return cuenta


def _auditar(engine, cuenta):
    with Session(engine) as db:
        evento = AuditService.log_event(
            db,
            cuenta,
            EventType.ACCOUNT_UPDATED.value,
            TargetType.ACCOUNT.value,
            actor_type=ActorType.SERVICE.value,
            target_id=cuenta,
            metadata={"campo": "account_type", "nuevo": "RESELLER"},
            auto_commit=True,
        )
        return evento.id


def test_auditar_genera_el_id(engine):
    cuenta = _cuenta(engine)

    assert _auditar(engine, cuenta) is not None


def test_los_dos_ids_tienen_default(engine):
    with engine.connect() as c:
        sin_default = c.execute(text("""
            SELECT table_name FROM information_schema.columns
             WHERE table_schema = 'public' AND column_name = 'id'
               AND table_name IN ('account_events', 'organization_capabilities')
               AND column_default IS NULL
            """)).scalars().all()
    assert sin_default == []


def test_antes_de_la_043_auditar_fallaba(engine):
    """Sin esto, el primer test probaría que un default genera un valor."""
    assert (
        desechable.alembic(BASE, "downgrade", REVISION_ANTERIOR) == 0
    ), "falló el downgrade a la 042"
    try:
        cuenta = _cuenta(engine)
        with pytest.raises(IntegrityError, match="account_events"):
            _auditar(engine, cuenta)
    finally:
        assert desechable.alembic(BASE, "upgrade", "head") == 0
