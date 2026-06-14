"""Construction tests for the Semantic Kernel agent layer (`sk_agents/`).

These assert the *wiring* — transport selection, specialist↔tool mapping, the LiteLLM
connector, and route mounting — with no network and no LLM call. Unlike ADK's `McpToolset`,
SK's MCP plugin connects eagerly (pruning to one tool needs the loaded tool list), so building
the agents is *not* offline-safe; the end-to-end run (live MCP server + live LLM) is the manual
demo, not pytest, to keep the suite hermetic. We therefore assert the static structure only.

The whole module is skipped when the optional `sk` extra isn't installed.
"""

from __future__ import annotations

import pytest

pytest.importorskip("semantic_kernel", reason="install with `uv sync --extra sk`")

from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.connectors.ai.open_ai import OpenAIChatPromptExecutionSettings
from semantic_kernel.connectors.mcp import MCPStdioPlugin, MCPStreamableHttpPlugin

from app.config import Settings, get_settings
from app.tools import REGISTRY


def test_connection_transport_default_is_streamable_http():
    from sk_agents.pagila_support.mcp_plugin import _new_plugin

    plugin = _new_plugin(Settings(sk_mcp_transport="http", sk_mcp_url="http://127.0.0.1:8765/mcp"))
    assert isinstance(plugin, MCPStreamableHttpPlugin)


def test_connection_transport_stdio_when_configured():
    from sk_agents.pagila_support.mcp_plugin import _new_plugin

    plugin = _new_plugin(Settings(sk_mcp_transport="stdio"))
    assert isinstance(plugin, MCPStdioPlugin)


def test_specs_cover_every_registry_tool():
    from sk_agents.pagila_support.specialists import SPECS

    # One specialist per tool, in lockstep with the registry — no more, no fewer.
    assert {spec.tool_name for spec in SPECS} == set(REGISTRY.keys())
    assert len({spec.name for spec in SPECS}) == len(REGISTRY)


def test_triage_instruction_lists_every_specialist():
    from sk_agents.pagila_support.agent import TRIAGE_INSTRUCTION
    from sk_agents.pagila_support.specialists import SPECS

    for spec in SPECS:
        assert spec.name in TRIAGE_INSTRUCTION


def test_litellm_connector_resolves_model_and_supports_tools():
    from sk_agents.pagila_support.llm import LiteLLMChatCompletion, build_service

    settings = Settings(anthropic_api_key="sk-test", llm_provider="anthropic")
    service = LiteLLMChatCompletion(settings, service_id="catalog_specialist")

    assert service.SUPPORTS_FUNCTION_CALLING is True
    assert service.ai_model_id == settings.litellm_model_string == "anthropic/claude-haiku-4-5"
    assert service.get_prompt_execution_settings_class() is OpenAIChatPromptExecutionSettings
    # The function-choice callback is the stock OpenAI-shaped one (LiteLLM speaks OpenAI).
    assert service._update_function_choice_settings_callback().__name__ == (
        "update_settings_from_function_call_configuration"
    )
    assert isinstance(build_service, object)  # importable


def test_connector_uses_active_provider_model_via_litellm_string():
    # Switching provider flows straight through litellm_model_string (no SK provider connector).
    from sk_agents.pagila_support.llm import LiteLLMChatCompletion

    openai_settings = Settings(openai_api_key="sk-test", llm_provider="openai")
    service = LiteLLMChatCompletion(openai_settings)
    assert service.ai_model_id == "openai/gpt-5.4-mini"


def test_auto_function_choice_is_constructible():
    # The behavior we attach to every agent so it can call its tool and issue handoffs.
    assert FunctionChoiceBehavior.Auto() is not None


def test_sk_route_is_mounted_when_installed():
    from app.api.main import create_app

    paths = {route.path for route in create_app().routes}
    assert "/sk/respond" in paths
