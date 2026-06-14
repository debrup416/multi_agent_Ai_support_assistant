"""RentalHistoryAgent — recent rentals (customer-scoped)."""

from __future__ import annotations

from app.llm.base import LLMClient
from app.schemas.contracts import AgentContext, AgentResult, Citation
from app.schemas.tools import RentalHistoryQuery
from app.tools import invoke
from app.tools.registry import GET_CUSTOMER_RENTAL_HISTORY

SYSTEM = """You are the rental-history specialist. Summarize ONLY the rentals provided for THIS \
customer — never invent titles or dates, never reveal another customer's data. If there are no \
rentals, say so. Be concise and courteous."""

_NEEDS_ID = (
    "I can't look up your rentals without knowing who you are. "
    "Please sign in or provide your customer id."
)


class RentalHistoryAgent:
    name = "RentalHistoryAgent"
    responsibility = "Recent rental questions for the requesting customer."
    tool_names = [GET_CUSTOMER_RENTAL_HISTORY.name]

    def handle(self, ctx: AgentContext, llm: LLMClient) -> AgentResult:
        if ctx.request.customer_id is None:
            return AgentResult(answer=_NEEDS_ID, tools_used=[], next_action="clarify")

        result = invoke(
            GET_CUSTOMER_RENTAL_HISTORY,
            RentalHistoryQuery(customer_id=ctx.request.customer_id),
        )
        tool = GET_CUSTOMER_RENTAL_HISTORY.name

        if not result.items:
            answer = llm.complete(
                system=SYSTEM,
                prompt=f'Customer asked: "{ctx.request.message}". This customer has no rentals '
                f"on record. Tell them no recent rentals were found.",
            )
            return AgentResult(answer=answer, tools_used=[tool], citations=[])

        def _fmt(item) -> str:
            rented = item.rental_date.strftime("%Y-%m-%d")
            if item.return_date:
                return f"- {item.title} | rented={rented} | returned={item.return_date:%Y-%m-%d}"
            return f"- {item.title} | rented={rented} | not yet returned"

        data = "\n".join(_fmt(i) for i in result.items)
        answer = llm.complete(
            system=SYSTEM,
            prompt=f'Customer asked: "{ctx.request.message}"\n\nTheir recent rentals:\n{data}\n\n'
            f"Summarize using only this data.",
        )
        return AgentResult(
            answer=answer,
            tools_used=[tool],
            citations=[Citation(source=tool, snippet=f"{len(result.items)} recent rentals")],
        )
