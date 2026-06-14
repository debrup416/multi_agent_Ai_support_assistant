"""The five specialist agents — one bounded ``ChatCompletionAgent`` per MCP tool.

Mirrors ``adk_agents/pagila_support/specialists.py`` and the project's core principle ("a new
capability is a new bounded agent + tool, never a growing mega-prompt"): ``SPECS`` is the single
declarative source, built straight against ``app.tools.REGISTRY`` so the specialist set stays in
lockstep with the tools the MCP server exposes. Each specialist gets its own kernel with exactly
one MCP tool (see ``mcp_plugin.make_single_tool_plugin``), the shared LiteLLM service, and a
function-invocation filter that records which MCP tools were actually called.

Building a specialist is async (it connects a live MCP session), so the agents are created on
first use by the runner, not at import — which keeps construction offline-safe for tests.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from dataclasses import dataclass

from semantic_kernel import Kernel
from semantic_kernel.agents import ChatCompletionAgent
from semantic_kernel.connectors.ai import FunctionChoiceBehavior
from semantic_kernel.connectors.mcp import MCPPluginBase
from semantic_kernel.filters import FilterTypes, FunctionInvocationContext

from app.config import Settings, get_settings
from app.observability.logging import get_logger, log_event
from app.tools import REGISTRY

from .llm import build_service
from .mcp_plugin import PLUGIN_NAMESPACE, make_single_tool_plugin

_logger = get_logger("sk.tools")

# Collects the MCP tool names called during one run_query. A mutable list is placed in this
# ContextVar before the orchestration runs; the function-invocation filter appends to it. The
# list object is shared into the runtime's child tasks (contextvars copy the reference), so
# appends made deep inside an agent are visible to the runner that set it.
_tool_calls: ContextVar[list[str] | None] = ContextVar("sk_tool_calls", default=None)


def set_tool_collector(collector: list[str] | None):
    """Bind a fresh collector for the current run; returns the token to reset it."""
    return _tool_calls.set(collector)


def reset_tool_collector(token) -> None:
    _tool_calls.reset(token)


@dataclass(frozen=True)
class SpecialistSpec:
    """A specialist's identity and the single tool it owns."""

    name: str  # a valid identifier — the agent name
    tool_name: str  # the MCP tool this specialist is scoped to (a REGISTRY key)
    description: str  # routing hint the triage agent hands off on
    instruction: str  # the specialist's own system prompt


# The customer's id, when known, is composed into the task message by the runner (trusted, not
# verified — the same model as the REST/MCP/ADK paths); scoped specialists ask for it if absent.
SPECS: list[SpecialistSpec] = [
    SpecialistSpec(
        name="catalog_specialist",
        tool_name="search_film_catalog",
        description="Answers questions about films: availability, category, rating, rental price, streaming.",
        instruction=(
            "You answer questions about the film catalog. Call `search_film_catalog` with a "
            "concise title or keyword. Ground every statement (title, category, rating, rental "
            "rate, streaming availability) in the tool result — never invent a film or a value. "
            "If nothing matches, say so plainly."
        ),
    ),
    SpecialistSpec(
        name="subscription_specialist",
        tool_name="get_customer_streaming_subscription",
        description="Answers the customer's own streaming-subscription questions (plan, status, dates, auto-renew).",
        instruction=(
            "You answer the customer's streaming-subscription questions. The customer's id, when "
            "known, is given in the conversation context; if it is missing, ask the customer for "
            "their customer id instead of guessing. Otherwise call "
            "`get_customer_streaming_subscription` and report plan, status, dates, and auto-renew "
            "strictly from the result. To *cancel* or change the subscription, do not act — hand "
            "off to the handoff specialist."
        ),
    ),
    SpecialistSpec(
        name="rental_history_specialist",
        tool_name="get_customer_rental_history",
        description="Reports the customer's own recent rental history.",
        instruction=(
            "You report the customer's recent rentals. The customer's id, when known, is given in "
            "the conversation context; if it is missing, ask for it. Otherwise call "
            "`get_customer_rental_history` and summarize the rentals it returns. Never fabricate "
            "titles or dates."
        ),
    ),
    SpecialistSpec(
        name="knowledge_specialist",
        tool_name="search_kb",
        description="Answers how-to and policy questions from the support knowledge base.",
        instruction=(
            "You answer how-to and policy questions from the support knowledge base. Call "
            "`search_kb` and base your answer only on the returned articles, citing them by title. "
            "If nothing relevant comes back, say you don't have an article covering it."
        ),
    ),
    SpecialistSpec(
        name="handoff_specialist",
        tool_name="create_handoff_ticket",
        description="Escalates to a human: cancellations, refunds, account closure, or anything unresolved.",
        instruction=(
            "You handle escalations to a human. When the customer wants to cancel, request a "
            "refund, close their account, or you otherwise cannot help, call "
            "`create_handoff_ticket` with a short summary and reason. Then confirm that a ticket "
            "was created and a human will follow up. You never perform the cancellation or refund "
            "yourself — creating the ticket is the action."
        ),
    ),
]


def _make_tool_tracking_filter() -> Callable[..., Awaitable[None]]:
    """An SK function-invocation filter: record + log each MCP tool call for this run."""

    async def _filter(context: FunctionInvocationContext, next: Callable[[FunctionInvocationContext], Awaitable[None]]):
        name = context.function.name
        collector = _tool_calls.get()
        if collector is not None and name in REGISTRY and name not in collector:
            collector.append(name)
        # Stamp the runtime onto handoff tickets so the operator sees who created them.
        if name == "create_handoff_ticket":
            context.arguments["source"] = "sk"
        log_event(_logger, "sk_tool_invocation", tool=name)
        await next(context)

    return _filter


async def build_specialist(
    spec: SpecialistSpec, settings: Settings | None = None
) -> tuple[ChatCompletionAgent, MCPPluginBase]:
    """Build one specialist agent; returns it with its live MCP plugin (for shutdown)."""
    s = settings or get_settings()
    plugin = await make_single_tool_plugin(spec.tool_name, s)

    kernel = Kernel()
    kernel.add_service(build_service(spec.name))
    kernel.add_filter(FilterTypes.FUNCTION_INVOCATION, _make_tool_tracking_filter())
    kernel.add_plugin(plugin, plugin_name=PLUGIN_NAMESPACE)

    agent = ChatCompletionAgent(
        name=spec.name,
        description=spec.description,
        instructions=spec.instruction,
        kernel=kernel,
        function_choice_behavior=FunctionChoiceBehavior.Auto(),
    )
    return agent, plugin
