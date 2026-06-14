"""Recent rental history business logic (customer-scoped)."""

from __future__ import annotations

from app.config import get_settings
from app.repository import connection
from app.repository.queries import get_rental_history
from app.schemas.tools import RentalHistoryItem, RentalHistoryResult


def get_customer_rental_history(
    customer_id: int, limit: int | None = None
) -> RentalHistoryResult:
    """Return the customer's most recent rentals; report ``truncated`` if capped."""
    limit = limit if limit is not None else get_settings().rental_history_limit
    with connection() as conn:
        rows = get_rental_history(conn, customer_id=customer_id, limit=limit)
    truncated = len(rows) > limit
    items = [RentalHistoryItem(**row) for row in rows[:limit]]
    return RentalHistoryResult(items=items, truncated=truncated)
