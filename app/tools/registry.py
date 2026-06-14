"""The fixed tool registry: five typed tools wrapping the service layer.

Each ``ToolSpec`` adapts the service function to a single-input-model callable and
carries its ownership/auth boundary. The agent binds to these specs and calls them
through ``app.tools.adapter.invoke``; the REST routes and MCP server use the same.
"""

from __future__ import annotations

from app import service
from app.schemas.tools import (
    FilmCatalogQuery,
    FilmCatalogResult,
    HandoffInput,
    HandoffResult,
    KbQuery,
    KbResult,
    RentalHistoryQuery,
    RentalHistoryResult,
    SubscriptionQuery,
    SubscriptionResult,
)
from app.tools.descriptors import ToolSpec

SEARCH_FILM_CATALOG = ToolSpec(
    name="search_film_catalog",
    description=(
        "Search the film catalog by title or keyword. Returns title, category, rating, "
        "rental rate, and streaming availability."
    ),
    input_model=FilmCatalogQuery,
    output_model=FilmCatalogResult,
    func=lambda inp: service.search_film_catalog(inp.query),
    auth_requirement="none",
    ownership_boundary="CatalogAgent; read-only over public catalog (Postgres).",
    is_empty=lambda out: not out.items,
)

GET_CUSTOMER_STREAMING_SUBSCRIPTION = ToolSpec(
    name="get_customer_streaming_subscription",
    description=(
        "Read the requesting customer's streaming subscription: status, plan, dates, "
        "and auto-renew."
    ),
    input_model=SubscriptionQuery,
    output_model=SubscriptionResult,
    func=lambda inp: service.get_customer_streaming_subscription(inp.customer_id),
    auth_requirement="customer_scope",
    ownership_boundary="SubscriptionAgent; read-only, scoped to the requesting customer.",
    is_empty=lambda out: not out.found,
)

GET_CUSTOMER_RENTAL_HISTORY = ToolSpec(
    name="get_customer_rental_history",
    description="Return the requesting customer's most recent rentals.",
    input_model=RentalHistoryQuery,
    output_model=RentalHistoryResult,
    func=lambda inp: service.get_customer_rental_history(inp.customer_id, inp.limit),
    auth_requirement="customer_scope",
    ownership_boundary="RentalHistoryAgent; read-only, scoped to the requesting customer.",
    is_empty=lambda out: not out.items,
)

SEARCH_KB = ToolSpec(
    name="search_kb",
    description="Search local support knowledge-base articles; returns source references.",
    input_model=KbQuery,
    output_model=KbResult,
    func=lambda inp: service.search_kb(inp.query),
    auth_requirement="none",
    ownership_boundary="KnowledgeAgent; read-only over local KB files.",
    is_empty=lambda out: not out.found,
)

CREATE_HANDOFF_TICKET = ToolSpec(
    name="create_handoff_ticket",
    description="Simulate escalating to human support by creating a handoff ticket.",
    input_model=HandoffInput,
    output_model=HandoffResult,
    func=lambda inp: service.create_handoff_ticket(
        inp.summary,
        inp.reason,
        customer_id=inp.customer_id,
        conversation_id=inp.conversation_id,
        source=inp.source,
    ),
    auth_requirement="none",
    ownership_boundary="HumanHandoffAgent; mock-write to the handoff sink only.",
)

REGISTRY: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        SEARCH_FILM_CATALOG,
        GET_CUSTOMER_STREAMING_SUBSCRIPTION,
        GET_CUSTOMER_RENTAL_HISTORY,
        SEARCH_KB,
        CREATE_HANDOFF_TICKET,
    )
}


def get_tool(name: str) -> ToolSpec | None:
    """Look up a tool spec by name."""
    return REGISTRY.get(name)
