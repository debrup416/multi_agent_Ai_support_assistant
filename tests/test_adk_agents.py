"""Construction tests for the Google ADK agent layer (`adk_agents/`).

These assert the *wiring* — transport selection, specialist↔tool mapping, coordinator
sub-agents, route mounting — with no network and no LLM call. ``McpToolset`` builds
lazily (tools are fetched from the server on first use), so constructing the agents is
offline-safe. End-to-end runs (live MCP server + live Claude) are the manual demo, not
pytest, to keep the suite hermetic.

The whole module is skipped when the optional ``adk`` extra isn't installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("google.adk", reason="install with `uv sync --extra adk`")

from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)

from app.config import Settings, get_settings
from app.tools import REGISTRY


def test_connection_params_default_is_streamable_http():
    from adk_agents.pagila_support.toolsets import connection_params

    cp = connection_params(
        Settings(adk_mcp_transport="http", adk_mcp_url="http://127.0.0.1:8765/mcp")
    )
    assert isinstance(cp, StreamableHTTPConnectionParams)
    assert cp.url == "http://127.0.0.1:8765/mcp"


def test_connection_params_stdio_when_configured():
    from adk_agents.pagila_support.toolsets import connection_params

    cp = connection_params(Settings(adk_mcp_transport="stdio"))
    assert isinstance(cp, StdioConnectionParams)
    assert cp.server_params.command == "python"
    assert cp.server_params.args == ["-m", "app.mcp.server"]


def test_specialists_cover_every_registry_tool():
    from adk_agents.pagila_support.specialists import SPECIALISTS, SPECS

    # One specialist per tool, in lockstep with the registry — no more, no fewer.
    assert {spec.tool_name for spec in SPECS} == set(REGISTRY.keys())
    assert len(SPECIALISTS) == len(REGISTRY)

    expected_model = get_settings().litellm_model_string
    for agent in SPECIALISTS:
        assert isinstance(agent.model, LiteLlm)
        assert agent.model.model == expected_model


def test_root_agent_wires_all_specialists():
    from adk_agents.pagila_support.agent import root_agent
    from adk_agents.pagila_support.specialists import SPECIALISTS

    assert root_agent.sub_agents == SPECIALISTS
    assert isinstance(root_agent.model, LiteLlm)


def test_adk_route_is_mounted_when_installed():
    from app.api.main import create_app

    paths = {route.path for route in create_app().routes}
    assert "/adk/respond" in paths
