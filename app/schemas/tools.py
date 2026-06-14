"""Typed input/output models for every tool.

These are the contracts the agent binds to in-process and the per-tool REST routes
expose over HTTP. JSON Schemas derived from these models populate the MCP
``ToolDescriptor`` metadata, so there is one definition per tool, reused everywhere.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

# --- search_film_catalog ------------------------------------------------------


class FilmCatalogQuery(BaseModel):
    query: str = Field(min_length=1, max_length=200, description="Title or keyword to search for.")


class FilmCatalogItem(BaseModel):
    title: str
    category: str | None = None
    rating: str | None = None
    rental_rate: Decimal
    streaming_available: bool


class FilmCatalogResult(BaseModel):
    items: list[FilmCatalogItem] = Field(default_factory=list)
    truncated: bool = False


# --- get_customer_streaming_subscription --------------------------------------


class SubscriptionQuery(BaseModel):
    customer_id: int = Field(ge=1, description="Customer whose subscription to read (scoped).")


class SubscriptionResult(BaseModel):
    found: bool
    plan_name: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    auto_renew: bool | None = None


# --- get_customer_rental_history ----------------------------------------------


class RentalHistoryQuery(BaseModel):
    customer_id: int = Field(ge=1, description="Customer whose rentals to read (scoped).")
    limit: int = Field(default=10, ge=1, le=50)


class RentalHistoryItem(BaseModel):
    title: str
    rental_date: datetime
    return_date: datetime | None = None


class RentalHistoryResult(BaseModel):
    items: list[RentalHistoryItem] = Field(default_factory=list)
    truncated: bool = False


# --- search_kb ----------------------------------------------------------------


class KbQuery(BaseModel):
    query: str = Field(min_length=1, max_length=200)


class KbArticle(BaseModel):
    id: str
    title: str
    snippet: str


class KbResult(BaseModel):
    found: bool
    results: list[KbArticle] = Field(default_factory=list)


# --- create_handoff_ticket ----------------------------------------------------


class HandoffInput(BaseModel):
    summary: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=200)
    customer_id: int | None = None
    conversation_id: str | None = None
    # Which runtime created the ticket: core | adk | sk. Defaults to "core"; the ADK/SK
    # layers stamp their own (they reach this tool over MCP).
    source: str = Field(default="core", max_length=20)


class HandoffResult(BaseModel):
    ticket_id: str
    status: str
    created_at: datetime
    summary: str
    reason: str
    source: str = "core"
