"""Request / result models for the Semantic Kernel chat seam.

Mirrors ``adk_agents.schemas`` so the new endpoint feels familiar. The result is
deliberately *leaner* than the core ``AgentResponse``: the SK path routes via LLM-driven
handoff (no deterministic router) and produces no schema/grounding ``guardrail_result``
it could stand behind, so it reports only what actually happened — the reply, which
specialist produced it, and which MCP tools were called.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkChatRequest(BaseModel):
    """Inbound request to ``POST /sk/respond`` (mirrors ``AdkChatRequest``)."""

    customer_id: int | None = Field(
        default=None,
        description="Trusted customer id (simplified auth). Null is handled gracefully.",
    )
    conversation_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class SkChatResult(BaseModel):
    """What the SK orchestration returns — only what it can actually attest to."""

    conversation_id: str
    reply: str
    selected_agent: str | None = Field(
        default=None,
        description="Name of the specialist that produced the final reply.",
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="MCP tool names invoked during the run, de-duplicated.",
    )
