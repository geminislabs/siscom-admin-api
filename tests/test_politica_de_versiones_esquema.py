"""La migración 047 crea la política de versiones sin cambiar nada al desplegar."""

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from tests import esquema_desechable as desechable

BASE = "siscom_test_politica_versiones"


@pytest.fixture(scope="module")
def engine():
    desechable.preparar(BASE, informar=False)
    eng = create_engine(desechable.url(BASE))
    yield eng
    eng.dispose()


def test_siembra_las_dos_plataformas_sin_minimo_ni_aviso(engine):
    with engine.connect() as c:
        filas = c.execute(text("""
                SELECT platform, min_supported_version, latest_version,
                       blocked_versions, updated_by
                  FROM public.client_version_policy ORDER BY platform
                """)).all()
    assert [tuple(f) for f in filas] == [
        ("android", None, None, [], "migracion 047"),
        ("ios", None, None, [], "migracion 047"),
    ]


def test_rechaza_una_plataforma_inventada(engine):
    with engine.connect() as c:
        tx = c.begin()
        try:
            with pytest.raises(IntegrityError):
                c.execute(
                    text(
                        "INSERT INTO public.client_version_policy (platform) VALUES ('web')"
                    )
                )
        finally:
            tx.rollback()
