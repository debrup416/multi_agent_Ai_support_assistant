"""SQLAlchemy engine: connection pool, per-statement timeout, read-only sessions.

The application engine opens **read-only** transactions at the Postgres level
(``default_transaction_read_only=on``). There is no code path from an agent or tool
to an ``UPDATE``/``DELETE`` on customer state — a write attempt errors at the database,
not merely by convention. (Alembic uses its own engine, so migrations are unaffected.)
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import Connection

from app.config import get_settings


@lru_cache
def get_engine() -> Engine:
    """Build the process-wide read-only engine from settings."""
    settings = get_settings()
    # psycopg passes `options` straight to the server as startup parameters.
    options = (
        f"-c statement_timeout={settings.db_statement_timeout_ms} "
        f"-c default_transaction_read_only=on"
    )
    return create_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_pre_ping=True,
        connect_args={"options": options},
    )


@contextmanager
def connection() -> Iterator[Connection]:
    """Yield a read-only connection, committing (read-only) on exit."""
    engine = get_engine()
    with engine.connect() as conn:
        yield conn
