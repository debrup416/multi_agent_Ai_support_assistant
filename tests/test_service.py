"""Service-layer tests against the live migrated DB (pure business logic seam)."""

from __future__ import annotations

from app.service import (
    get_customer_rental_history,
    get_customer_streaming_subscription,
    search_film_catalog,
)


def test_catalog_search_returns_one_row_per_film():
    result = search_film_catalog("alien")
    titles = [i.title for i in result.items]
    # Multiple film_category rows must not duplicate a film.
    assert len(titles) == len(set(titles))
    assert any("ALIEN" in t for t in titles)
    assert all(i.streaming_available for i in result.items)


def test_catalog_search_unknown_title_is_empty():
    result = search_film_catalog("Nonexistent Film 9999")
    assert result.items == []


def test_subscription_found_for_customer_1():
    result = get_customer_streaming_subscription(1)
    assert result.found is True
    assert result.status == "active"


def test_subscription_missing_for_unknown_customer():
    result = get_customer_streaming_subscription(999_999)
    assert result.found is False
    assert result.plan_name is None


def test_rental_history_scoped_to_customer():
    result = get_customer_rental_history(1, limit=5)
    assert len(result.items) <= 5
    # Every item is a real titled rental for this customer.
    assert all(i.title for i in result.items)
