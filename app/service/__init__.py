"""Core business logic — the single source of truth behind tools and REST routes.

Services contain no Pydantic-tool framing or HTTP concerns; they query the
repository / KB files / mock sink and return typed result models. Both the in-process
tool wrappers (``app.tools``) and the per-tool REST routes call into here.
"""

from app.service.catalog import search_film_catalog
from app.service.handoff import (
    create_handoff_ticket,
    get_handoff_ticket,
    list_handoff_tickets,
)
from app.service.kb import get_kb_article, list_kb_articles, search_kb
from app.service.rentals import get_customer_rental_history
from app.service.subscription import get_customer_streaming_subscription

__all__ = [
    "search_film_catalog",
    "get_customer_streaming_subscription",
    "get_customer_rental_history",
    "search_kb",
    "list_kb_articles",
    "get_kb_article",
    "create_handoff_ticket",
    "list_handoff_tickets",
    "get_handoff_ticket",
]
