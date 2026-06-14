"""MCP connection wiring for the ADK specialists.

Every specialist reaches the tools through the ``pagila-support-mcp`` server (the same
server ``app/mcp/server.py`` serves). The transport is chosen once, from settings:
streamable HTTP by default (connect to a running server), or stdio (ADK spawns
``python -m app.mcp.server`` itself). ``make_toolset`` builds a single-tool view via
``tool_filter`` so each specialist only sees its own tool.
"""

from __future__ import annotations

from . import env  # noqa: F401  -- side effect: load repo-root .env before anything reads it

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import (
    StdioConnectionParams,
    StreamableHTTPConnectionParams,
)
from mcp import StdioServerParameters

from app.config import Settings, get_settings


def connection_params(
    settings: Settings | None = None,
) -> StreamableHTTPConnectionParams | StdioConnectionParams:
    """Build MCP connection params for the configured transport.

    Pass an explicit ``settings`` in tests; production reads the cached singleton.
    """
    s = settings or get_settings()
    if s.adk_mcp_transport == "stdio":
        return StdioConnectionParams(
            server_params=StdioServerParameters(
                command="python", args=["-m", "app.mcp.server"]
            ),
            timeout=15,
        )
    return StreamableHTTPConnectionParams(url=s.adk_mcp_url)


def make_toolset(tool_name: str) -> McpToolset:
    """A toolset exposing exactly one tool from the MCP server."""
    return McpToolset(connection_params=connection_params(), tool_filter=[tool_name])
