"""Read-only SQLAlchemy access over the Pagila database."""

from app.repository.engine import connection, get_engine

__all__ = ["connection", "get_engine"]
