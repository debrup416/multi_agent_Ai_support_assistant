"""Tool-layer tests: typed contracts, descriptors, and the adapter."""

from __future__ import annotations

from app.schemas.tools import FilmCatalogQuery, FilmCatalogResult, SubscriptionQuery
from app.tools import REGISTRY, invoke
from app.tools.registry import GET_CUSTOMER_STREAMING_SUBSCRIPTION, SEARCH_FILM_CATALOG


def test_every_tool_has_a_valid_descriptor():
    for name, spec in REGISTRY.items():
        d = spec.descriptor()
        assert d.name == name
        assert d.description
        assert d.input_schema["type"] == "object"
        assert d.output_schema
        assert d.auth_requirement in {"none", "customer_scope"}
        assert d.ownership_boundary


def test_invoke_returns_typed_output():
    out = invoke(SEARCH_FILM_CATALOG, FilmCatalogQuery(query="alien"))
    assert isinstance(out, FilmCatalogResult)
    assert out.items


def test_customer_scoped_tool_filters_by_customer():
    found = invoke(GET_CUSTOMER_STREAMING_SUBSCRIPTION, SubscriptionQuery(customer_id=1))
    missing = invoke(
        GET_CUSTOMER_STREAMING_SUBSCRIPTION, SubscriptionQuery(customer_id=999_999)
    )
    assert found.found is True
    assert missing.found is False
