"""Streaming subscription lookup business logic (customer-scoped)."""

from __future__ import annotations

from app.repository import connection
from app.repository.queries import get_subscription
from app.schemas.tools import SubscriptionResult


def get_customer_streaming_subscription(customer_id: int) -> SubscriptionResult:
    """Return the customer's current subscription, or ``found=False`` if none."""
    with connection() as conn:
        row = get_subscription(conn, customer_id=customer_id)
    if row is None:
        return SubscriptionResult(found=False)
    return SubscriptionResult(found=True, **row)
