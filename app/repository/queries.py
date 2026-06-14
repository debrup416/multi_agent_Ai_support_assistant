"""All SQL lives here, as parametrized read-only statements.

Tools and services call these functions; they never assemble SQL themselves. Every
statement uses bind parameters (no f-strings/concatenation into SQL), keeping the
injection surface to parameters only. Each query fetches ``limit + 1`` rows where
relevant so the caller can report ``truncated`` without a second count query.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection

# --- film catalog -------------------------------------------------------------

_FILM_CATALOG_SQL = text(
    """
    SELECT f.title,
           (
               SELECT c.name
               FROM film_category fc
               JOIN category c ON c.category_id = fc.category_id
               WHERE fc.film_id = f.film_id
               ORDER BY c.name
               LIMIT 1
           )              AS category,
           f.rating::text AS rating,
           f.rental_rate,
           f.streaming_available
    FROM film f
    WHERE f.title ILIKE :pattern
    ORDER BY f.title
    LIMIT :limit
    """
)


def search_films(conn: Connection, *, query: str, limit: int) -> list[dict]:
    """Case-insensitive title search. Fetches one extra row to detect truncation."""
    rows = conn.execute(
        _FILM_CATALOG_SQL, {"pattern": f"%{query}%", "limit": limit + 1}
    ).mappings()
    return [dict(r) for r in rows]


# --- streaming subscription ---------------------------------------------------

_SUBSCRIPTION_SQL = text(
    """
    SELECT plan_name, status, start_date, end_date, auto_renew
    FROM streaming_subscription
    WHERE customer_id = :customer_id
    ORDER BY start_date DESC
    LIMIT 1
    """
)


def get_subscription(conn: Connection, *, customer_id: int) -> dict | None:
    """Most recent subscription row for a customer, or None."""
    row = conn.execute(_SUBSCRIPTION_SQL, {"customer_id": customer_id}).mappings().first()
    return dict(row) if row is not None else None


# --- rental history -----------------------------------------------------------

_RENTAL_HISTORY_SQL = text(
    """
    SELECT f.title, r.rental_date, r.return_date
    FROM rental r
    JOIN inventory i ON i.inventory_id = r.inventory_id
    JOIN film f      ON f.film_id = i.film_id
    WHERE r.customer_id = :customer_id
    ORDER BY r.rental_date DESC
    LIMIT :limit
    """
)


def get_rental_history(conn: Connection, *, customer_id: int, limit: int) -> list[dict]:
    """Recent rentals for a customer (customer→rental→inventory→film join)."""
    rows = conn.execute(
        _RENTAL_HISTORY_SQL, {"customer_id": customer_id, "limit": limit + 1}
    ).mappings()
    return [dict(r) for r in rows]
