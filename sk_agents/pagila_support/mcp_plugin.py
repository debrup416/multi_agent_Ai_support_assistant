"""MCP connection wiring for the Semantic Kernel specialists.

Mirrors ``adk_agents/pagila_support/toolsets.py``: the transport is chosen once from
settings — streamable HTTP by default (connect to a running ``pagila-support-mcp`` server),
or stdio (SK spawns ``python -m app.mcp.server`` itself).

SK's MCP plugins have no per-tool filter (only a boolean ``load_tools``), so to give each
specialist exactly one tool we connect one plugin per specialist and prune it. Connecting
runs ``MCPPluginBase.load_tools``, which ``setattr``s a ``kernel_function`` per server tool
onto the plugin; we then delete every tool attribute except the owned one, so when the
plugin is added to that specialist's kernel only its single tool is exposed.
"""

from __future__ import annotations

from typing import Any

from semantic_kernel.connectors.mcp import (
    MCPPluginBase,
    MCPStdioPlugin,
    MCPStreamableHttpPlugin,
)

from app.config import Settings, get_settings
from app.tools import REGISTRY

# All specialists share one kernel-plugin namespace; each lives in its own kernel, so the
# (plugin, tool) pair is unambiguous. The fully-qualified tool the model sees is
# ``pagila-<tool_name>`` (SK joins plugin + function with a hyphen).
PLUGIN_NAMESPACE = "pagila"


# The InProcessRuntime deep-copies each agent (and its kernel) when it instantiates the agent
# as an actor; that recurses into our MCP plugin, whose live session holds async generators
# that cannot be deep-copied. The session is meant to be *shared*, not duplicated, so we make
# the plugin return itself on deepcopy — the actor copies all reference the one live session.
class _SharedStreamableHttpPlugin(MCPStreamableHttpPlugin):
    def __deepcopy__(self, memo: dict[int, Any]) -> "_SharedStreamableHttpPlugin":
        memo[id(self)] = self
        return self


class _SharedStdioPlugin(MCPStdioPlugin):
    def __deepcopy__(self, memo: dict[int, Any]) -> "_SharedStdioPlugin":
        memo[id(self)] = self
        return self


def _new_plugin(settings: Settings) -> MCPPluginBase:
    """An (unconnected) MCP plugin for the configured transport (deepcopy-shared session)."""
    if settings.sk_mcp_transport == "stdio":
        return _SharedStdioPlugin(
            name=PLUGIN_NAMESPACE,
            command="python",
            args=["-m", "app.mcp.server"],
            load_prompts=False,
            request_timeout=15,
        )
    return _SharedStreamableHttpPlugin(
        name=PLUGIN_NAMESPACE,
        url=settings.sk_mcp_url,
        load_prompts=False,
    )


async def make_single_tool_plugin(
    tool_name: str, settings: Settings | None = None
) -> MCPPluginBase:
    """Connect an MCP plugin and prune it to exactly one tool (``tool_name``).

    The returned plugin holds a live MCP session — the caller owns its lifecycle and must
    ``await plugin.close()`` on shutdown.
    """
    s = settings or get_settings()
    plugin = _new_plugin(s)
    await plugin.connect()  # loads every server tool as an attribute on `plugin`
    # Drop every other tool so this plugin exposes only its owned one to its agent's kernel.
    for other in REGISTRY:
        if other != tool_name and hasattr(plugin, other):
            delattr(plugin, other)
    return plugin
