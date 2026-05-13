"""Smoke test para app.db.base (metadata Alembic/SQLModel)."""

from sqlmodel import SQLModel

import app.db.base as db_base


def test_base_aliases_sqlmodel_metadata():
    assert db_base.Base is SQLModel.metadata
