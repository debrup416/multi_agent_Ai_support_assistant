"""SubscriptionAgent — subscription status & renewal (customer-scoped)."""

from __future__ import annotations

from app.llm.base import LLMClient
from app.schemas.contracts import AgentContext, AgentResult, Citation
from app.schemas.tools import SubscriptionQuery
from app.tools import invoke
from app.tools.registry import GET_CUSTOMER_STREAMING_SUBSCRIPTION

SYSTEM = """You are the subscription specialist. Answer ONLY from the subscription data provided for \
THIS customer. Never reveal another customer's data. State the plan, status, renewal/end date, and \
auto-renew when present. If no subscription exists, say so plainly. Be concise and courteous."""

_NEEDS_ID = (
    "I can't look up your subscription without knowing who you are. "
    "Please sign in or provide your customer id."
)


class SubscriptionAgent:
    name = "SubscriptionAgent"
    responsibility = "Subscription status & renewal questions for the requesting customer."
    tool_names = [GET_CUSTOMER_STREAMING_SUBSCRIPTION.name]

    def handle(self, ctx: AgentContext, llm: LLMClient) -> AgentResult:
        if ctx.request.customer_id is None:
            # Defense in depth; the input guardrail normally handles this first.
            return AgentResult(answer=_NEEDS_ID, tools_used=[], next_action="clarify")

        result = invoke(
            GET_CUSTOMER_STREAMING_SUBSCRIPTION,
            SubscriptionQuery(customer_id=ctx.request.customer_id),
        )
        tool = GET_CUSTOMER_STREAMING_SUBSCRIPTION.name

        if not result.found:
            answer = llm.complete(
                system=SYSTEM,
                prompt=f'Customer asked: "{ctx.request.message}". This customer has no '
                f"subscription on record. Tell them no active subscription was found.",
            )
            return AgentResult(answer=answer, tools_used=[tool], citations=[])

        data = (
            f"plan={result.plan_name}; status={result.status}; start_date={result.start_date}; "
            f"end_date={result.end_date}; auto_renew={result.auto_renew}"
        )
        answer = llm.complete(
            system=SYSTEM,
            prompt=f'Customer asked: "{ctx.request.message}"\n\nTheir subscription:\n{data}\n\n'
            f"Answer using only this data.",
        )
        return AgentResult(
            answer=answer,
            tools_used=[tool],
            citations=[Citation(source=tool, snippet=data)],
        )
