"""The five specialist sub-agents — one bounded agent per MCP tool.

This mirrors the project's core principle ("a new capability is a new bounded agent +
tool, never a growing mega-prompt"): each specialist is given exactly one tool via an
``McpToolset`` ``tool_filter`` and an instruction scoped to that job. ``SPECS`` is the
single declarative source — built straight against ``app.tools.REGISTRY`` so the set of
specialists stays in lockstep with the tools the MCP server actually exposes.
"""

from __future__ import annotations

from dataclasses import dataclass

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool import McpToolset

from app.config import get_settings
from app.tools import REGISTRY

from .toolsets import make_toolset


@dataclass(frozen=True)
class SpecialistSpec:
    """A specialist's identity and the single tool it owns."""

    name: str  # a valid identifier — ADK agent name
    tool_name: str  # the MCP tool this specialist is scoped to (a REGISTRY key)
    description: str  # routing hint the coordinator uses to delegate
    instruction: str  # the specialist's own system prompt


# Customer-scoped specialists read {customer_id?} from session state (the runner injects
# it). It is intentionally trusted, not verified — the same model as the REST/MCP paths.
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
            "You answer the customer's streaming-subscription questions. The current customer_id "
            "is '{customer_id?}'. If that is empty, ask the customer for their customer id instead "
            "of guessing. Otherwise call `get_customer_streaming_subscription` and report plan, "
            "status, dates, and auto-renew strictly from the result. To *cancel* or change the "
            "subscription, do not act — hand off to the human-handoff specialist."
        ),
    ),
    SpecialistSpec(
        name="rental_history_specialist",
        tool_name="get_customer_rental_history",
        description="Reports the customer's own recent rental history.",
        instruction=(
            "You report the customer's recent rentals. The current customer_id is '{customer_id?}'. "
            "If that is empty, ask for it. Otherwise call `get_customer_rental_history` and "
            "summarize the rentals it returns. Never fabricate titles or dates."
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


def build_model() -> LiteLlm:
    """The shared model for all specialists, resolved from Settings the same way as the
    core path: provider auto-detected from the API keys (``anthropic/<model>`` or
    ``openai/<model>``), overridable via ``LLM_PROVIDER``. The key is passed explicitly
    so we do not depend solely on env vars being exported."""
    settings = get_settings()
    return LiteLlm(
        model=settings.litellm_model_string,
        api_key=settings.active_api_key.get_secret_value(),
    )


def _stamp_source(tool, args, tool_context):  # noqa: ANN001, ARG001 -- ADK before_tool_callback
    """Tag handoff tickets with the runtime so the operator sees who created them."""
    if tool.name == "create_handoff_ticket":
        args["source"] = "adk"
    return None


def _build(spec: SpecialistSpec) -> tuple[LlmAgent, McpToolset]:
    toolset = make_toolset(spec.tool_name)
    agent = LlmAgent(
        name=spec.name,
        model=build_model(),
        description=spec.description,
        instruction=spec.instruction,
        tools=[toolset],
        before_tool_callback=_stamp_source,
    )
    return agent, toolset


_built = [_build(spec) for spec in SPECS]
SPECIALISTS: list[LlmAgent] = [agent for agent, _ in _built]
# Kept so the runtime can close the live MCP sessions on shutdown.
TOOLSETS: list[McpToolset] = [toolset for _, toolset in _built]
