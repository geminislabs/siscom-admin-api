"""
Tests de `scripts/seed_gac_system_user.py`.

El script escribía `organization_id`, que desde la migración 036 es una
propiedad sin setter, y nadie lo notó porque ningún test lo ejecutaba.
"""

import importlib.util
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from app.models.user import User, UserStatus

_RUTA = Path(__file__).resolve().parent.parent / "scripts" / "seed_gac_system_user.py"


def _cargar_script():
    spec = importlib.util.spec_from_file_location("seed_gac_system_user", _RUTA)
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture
def seed(db_session, monkeypatch):
    """El script con `SessionLocal` apuntando a la sesión del test.

    `close()` se anula para que el script no cierre la sesión que el fixture
    revierte al terminar.
    """
    modulo = _cargar_script()
    monkeypatch.setattr(db_session, "close", lambda: None)
    monkeypatch.setattr(modulo, "SessionLocal", lambda: db_session)

    def correr(*args):
        monkeypatch.setattr(sys, "argv", ["seed_gac_system_user.py", *args])
        return modulo.main()

    return correr


def _usuario_sistema(db_session):
    return (
        db_session.query(User)
        .filter(User.email == _cargar_script().GAC_SYSTEM_EMAIL)
        .all()
    )


def test_crea_el_usuario_inactivo_en_la_organizacion_indicada(
    seed, db_session, test_organization_data, capsys
):
    assert seed("--organization-id", str(test_organization_data.id)) == 0

    [usuario] = _usuario_sistema(db_session)
    assert usuario.default_organization_id == test_organization_data.id
    assert usuario.status == UserStatus.INACTIVE.value
    assert f"GAC_SYSTEM_USER_ID={usuario.id}" in capsys.readouterr().out


def test_es_idempotente(seed, db_session, test_organization_data, capsys):
    seed("--organization-id", str(test_organization_data.id))
    [primero] = _usuario_sistema(db_session)
    capsys.readouterr()

    assert seed("--organization-id", str(test_organization_data.id)) == 0

    assert [u.id for u in _usuario_sistema(db_session)] == [primero.id]
    assert f"GAC_SYSTEM_USER_ID={primero.id}" in capsys.readouterr().out


def test_organizacion_inexistente_no_crea_nada(
    seed, db_session, test_organization_data
):
    assert seed("--organization-id", str(uuid4())) == 1

    assert _usuario_sistema(db_session) == []


def test_exige_la_organizacion(seed, test_organization_data):
    with pytest.raises(SystemExit):
        seed()
