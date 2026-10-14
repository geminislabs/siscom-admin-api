"""Publicar y descartar dejan `tenant_branding.draft` en NULL de SQL.

Con `Column(JSONB)` a secas, asignar `None` escribe el JSON `'null'`, y el
`CHECK (draft IS NULL OR jsonb_typeof(draft) = 'object')` de la `027` lo
rechaza: publicar y descartar respondían 500 en producción. Va como test de
esquema porque el harness normal crea la tabla con `create_all()`, que no trae
ese CHECK.
"""

from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlmodel import Session

from app.models.tenancy import TenantBranding
from tests import esquema_desechable as desechable

BASE = "siscom_test_borrador_nulo"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def test_quitar_el_borrador_lo_deja_en_null(engine):
    cuenta = uuid4()
    with engine.begin() as c:
        c.execute(
            text(
                "INSERT INTO public.accounts (id, account_name) VALUES (:id, 'Marca')"
            ),
            {"id": cuenta},
        )

    with Session(engine) as db:
        db.add(TenantBranding(account_id=cuenta, draft={"brand_name": "Marca"}))
        db.commit()

    # Lo mismo que hacen `publicar` y `descartar_borrador`.
    with Session(engine) as db:
        fila = db.get(TenantBranding, cuenta)
        fila.published = {"seed": {"primary": "#2563eb"}}
        fila.draft = None
        db.commit()

    with engine.connect() as c:
        es_null = c.execute(
            text(
                "SELECT draft IS NULL FROM public.tenant_branding WHERE account_id = :id"
            ),
            {"id": cuenta},
        ).scalar_one()
    assert es_null is True
