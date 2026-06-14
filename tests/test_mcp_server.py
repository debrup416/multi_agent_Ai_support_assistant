"""MCP transport tests: the registry exposed over the Model Context Protocol.

These drive the low-level server through the SDK's in-memory client session, so no
subprocess or socket is involved. `test_list_tools_*` needs no database; the
`call_tool` tests query live Postgres, same prerequisite as `test_tools.py`.
"""

from __future__ import annotations

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from app.mcp.server import server
from app.schemas.tools import FilmCatalogResult, SubscriptionResult
from app.tools import REGISTRY


@pytest.mark.asyncio
async def test_list_tools_exposes_every_registry_tool():
    async with create_connected_server_and_client_session(server) as client:
        result = await client.list_tools()

    listed = {tool.name: tool for tool in result.tools}
    assert listed.keys() == REGISTRY.keys()
    for name, tool in listed.items():
        spec = REGISTRY[name]
        assert tool.description == spec.description
        assert tool.inputSchema == spec.descriptor().input_schema
        assert tool.inputSchema["type"] == "object"
        assert tool.outputSchema == spec.descriptor().output_schema


@pytest.mark.asyncio
async def test_call_tool_returns_structured_and_text_content():
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("search_film_catalog", {"query": "alien"})

    assert result.isError is False
    # Structured payload round-trips back into the tool's typed result model.
    parsed = FilmCatalogResult.model_validate(result.structuredContent)
    assert parsed.items
    # The same data is mirrored as a JSON text block for plain clients.
    assert result.content and result.content[0].text


@pytest.mark.asyncio
async def test_call_tool_scopes_to_the_requested_customer():
    async with create_connected_server_and_client_session(server) as client:
        found = await client.call_tool(
            "get_customer_streaming_subscription", {"customer_id": 1}
        )
        missing = await client.call_tool(
            "get_customer_streaming_subscription", {"customer_id": 999_999}
        )

    assert SubscriptionResult.model_validate(found.structuredContent).found is True
    assert SubscriptionResult.model_validate(missing.structuredContent).found is False


@pytest.mark.asyncio
async def test_call_tool_unknown_name_is_an_error():
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("no_such_tool", {})
    assert result.isError is True


@pytest.mark.asyncio
async def test_call_tool_rejects_input_that_violates_the_schema():
    # query has min_length=1; an empty string must fail validation, not reach the DB.
    async with create_connected_server_and_client_session(server) as client:
        result = await client.call_tool("search_film_catalog", {"query": ""})
    assert result.isError is True
