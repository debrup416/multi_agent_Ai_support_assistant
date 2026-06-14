"""The Agent contract.

Every agent owns a narrow slice of the problem: a short system prompt, its bound
tool(s), and a typed result. The orchestrator passes the shared :class:`LLMClient`
into ``handle`` so agents stay stateless and unit-testable with a fake client.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.llm.base import LLMClient
from app.schemas.contracts import AgentContext, AgentResult


@runtime_checkable
class Agent(Protocol):
    name: str
    responsibility: str
    tool_names: list[str]

    def handle(self, ctx: AgentContext, llm: LLMClient) -> AgentResult: ...
