"""Tool routes.

`GET /tools` and `GET /tools/{name}` expose the MCP-ready descriptors. The explicit
per-tool POST routes let a human exercise each tool from Swagger with its real typed
body; each delegates to the same `tools/` wrapper the agent uses (tool -> service),
so a green call here proves the agent's data path.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

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
from app.tools import REGISTRY, ToolDescriptor, get_tool, invoke
from app.tools.registry import (
    CREATE_HANDOFF_TICKET,
    GET_CUSTOMER_RENTAL_HISTORY,
    GET_CUSTOMER_STREAMING_SUBSCRIPTION,
    SEARCH_FILM_CATALOG,
    SEARCH_KB,
)

router = APIRouter(tags=["tools"])


@router.get("/tools", response_model=list[ToolDescriptor])
def list_tools() -> list[ToolDescriptor]:
    """List every tool's MCP-ready descriptor."""
    return [spec.descriptor() for spec in REGISTRY.values()]


@router.get("/tools/{name}", response_model=ToolDescriptor)
def get_tool_descriptor(name: str) -> ToolDescriptor:
    """One tool's descriptor (name, description, in/out JSON schema, boundaries)."""
    spec = get_tool(name)
    if spec is None:
        raise HTTPException(status_code=404, detail=f"Unknown tool: {name}")
    return spec.descriptor()


# --- explicit per-tool invocation (typed bodies for Swagger) ------------------


@router.post("/tools/search_film_catalog", response_model=FilmCatalogResult)
def call_search_film_catalog(payload: FilmCatalogQuery) -> FilmCatalogResult:
    return invoke(SEARCH_FILM_CATALOG, payload)  # type: ignore[return-value]


@router.post(
    "/tools/get_customer_streaming_subscription", response_model=SubscriptionResult
)
def call_get_subscription(payload: SubscriptionQuery) -> SubscriptionResult:
    return invoke(GET_CUSTOMER_STREAMING_SUBSCRIPTION, payload)  # type: ignore[return-value]


@router.post("/tools/get_customer_rental_history", response_model=RentalHistoryResult)
def call_get_rentals(payload: RentalHistoryQuery) -> RentalHistoryResult:
    return invoke(GET_CUSTOMER_RENTAL_HISTORY, payload)  # type: ignore[return-value]


@router.post("/tools/search_kb", response_model=KbResult)
def call_search_kb(payload: KbQuery) -> KbResult:
    return invoke(SEARCH_KB, payload)  # type: ignore[return-value]


@router.post("/tools/create_handoff_ticket", response_model=HandoffResult)
def call_create_handoff_ticket(payload: HandoffInput) -> HandoffResult:
    return invoke(CREATE_HANDOFF_TICKET, payload)  # type: ignore[return-value]
