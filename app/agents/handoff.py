"""HumanHandoffAgent — escalation & risky requests.

Creates a (mock) handoff ticket. It never performs sensitive account changes itself;
it records the request for a human to action.
"""

from __future__ import annotations

from app.llm.base import LLMClient
from app.schemas.contracts import AgentContext, AgentResult, Citation
from app.schemas.tools import HandoffInput
from app.tools import invoke
from app.tools.registry import CREATE_HANDOFF_TICKET


class HumanHandoffAgent:
    name = "HumanHandoffAgent"
    responsibility = "Escalation and risky/sensitive requests; creates a handoff ticket."
    tool_names = [CREATE_HANDOFF_TICKET.name]

    def handle(self, ctx: AgentContext, llm: LLMClient) -> AgentResult:
        reason = str(ctx.scratch.get("handoff_reason", "customer_requested_human"))
        result = invoke(
            CREATE_HANDOFF_TICKET,
            HandoffInput(
                summary=ctx.request.message[:500],
                reason=reason,
                customer_id=ctx.request.customer_id,
                conversation_id=ctx.request.conversation_id,
            ),
        )
        tool = CREATE_HANDOFF_TICKET.name
        answer = (
            f"I've escalated this to our support team (ticket {result.ticket_id}). "
            "A human agent will follow up with you. For your security, account changes "
            "like cancellations or refunds are handled by a person, not automatically."
        )
        return AgentResult(
            answer=answer,
            tools_used=[tool],
            citations=[Citation(source=tool, snippet=result.ticket_id)],
            next_action="handoff",
        )
