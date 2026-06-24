"""SQLite compatibility shims for PostgreSQL types used in tests."""

from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles

_REGISTERED = False


@compiles(JSONB, "sqlite")
def _compile_jsonb_for_sqlite(type_, compiler, **kw):
    """Keep JSONB query operators (.astext, ->>) while storing as SQLite JSON."""
    return "JSON"


def register_sqlite_dialect_compat() -> None:
    """Idempotent registration of SQLite compile hooks for PG types."""
    global _REGISTERED
    _REGISTERED = True
