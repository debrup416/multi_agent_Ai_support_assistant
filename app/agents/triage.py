"""TriageAgent — a single constrained LLM classification call."""

from __future__ import annotations

from app.llm.base import LLMClient
from app.schemas.contracts import AgentContext, TriageDecision

TRIAGE_SYSTEM = """You are a triage classifier for a streaming + rental platform's support \
assistant. Classify the customer's message into exactly one intent and pick the matching agent.

Intents and their agents:
- catalog_search -> CatalogAgent: films, titles, genres, ratings, prices, streaming availability.
- subscription_question -> SubscriptionAgent: the customer's own subscription status, plan, renewal.
- rental_history -> RentalHistoryAgent: the customer's own past or recent rentals.
- knowledge_question -> KnowledgeAgent: general how-to / account / policy help (e.g. updating payment method).
- human_handoff -> HumanHandoffAgent: wants a human, OR requests a sensitive account change \
(cancel, refund, change payment, close account).

Return the intent, the matching selected_agent, a confidence between 0 and 1, and a short reason. \
Use lower confidence when the message is vague or could fit multiple intents."""


def triage(ctx: AgentContext, llm: LLMClient) -> TriageDecision:
    """Classify the message into a structured :class:`TriageDecision`."""
    return llm.complete_structured(
        system=TRIAGE_SYSTEM,
        prompt=f"Customer message:\n{ctx.request.message}",
        schema=TriageDecision,
        max_tokens=256,
    )
