"""Tests for SQLite dialect compatibility used by the test harness."""

from sqlalchemy import Column, MetaData, Table, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB

from tests.sqlite_dialect import register_sqlite_dialect_compat


def test_jsonb_astext_query_on_sqlite():
    register_sqlite_dialect_compat()

    metadata = MetaData()
    table = Table(
        "commands",
        metadata,
        Column("command_metadata", JSONB),
    )
    engine = create_engine("sqlite:///:memory:")
    metadata.create_all(engine)

    with engine.begin() as conn:
        conn.execute(
            table.insert(),
            {"command_metadata": {"source_id": "user_commands", "unit_id": "u1"}},
        )
        stmt = select(table).where(
            table.c.command_metadata["source_id"].astext == "user_commands"
        )
        row = conn.execute(stmt).first()
        assert row is not None
