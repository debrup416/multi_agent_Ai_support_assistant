"""Migration tests — the migrated schema and seed are present on the live DB.

Assumes a Pagila restore with `alembic upgrade head` applied (see README).
"""

from __future__ import annotations

from sqlalchemy import text

from app.repository import connection


def test_film_streaming_available_column_exists():
    with connection() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name='film' AND column_name='streaming_available'"
            )
        ).scalar()
    assert exists == 1


def test_some_films_are_streamable():
    with connection() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM film WHERE streaming_available")
        ).scalar()
    assert count and count > 0


def test_streaming_subscription_table_and_seed():
    with connection() as conn:
        row = conn.execute(
            text(
                "SELECT plan_name, status FROM streaming_subscription "
                "WHERE customer_id = 1 ORDER BY start_date DESC LIMIT 1"
            )
        ).mappings().first()
    assert row is not None
    assert row["status"] == "active"
