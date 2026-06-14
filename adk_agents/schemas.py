"""Request / result models for the ADK chat seam.

The request mirrors ``app.schemas.contracts.AgentRequest`` so the new endpoint feels
familiar. The result is deliberately *leaner* than ``AgentResponse``: the ADK path has no
deterministic router or output guardrail, so it does not invent ``confidence`` or a
``guardrail_result`` it cannot stand behind. It reports only what actually happened —
the reply, which specialist produced it, and which MCP tools were called.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AdkChatRequest(BaseModel):
    """Inbound request to ``POST /adk/respond`` (mirrors ``AgentRequest``)."""

    customer_id: int | None = Field(
        default=None,
        description="Trusted customer id (simplified auth). Null is handled gracefully.",
    )
    conversation_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class AdkChatResult(BaseModel):
    """What the ADK coordinator returns — only what it can actually attest to."""

    conversation_id: str
    reply: str
    selected_agent: str | None = Field(
        default=None,
        description="Name of the sub-agent that produced the final reply (event author).",
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="MCP tool names invoked during the run, de-duplicated.",
    )
