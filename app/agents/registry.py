"""Deterministic routing registry.

The LLM produces only the classification (``TriageDecision``); dispatch is a plain
dict lookup here. Low-confidence or unknown intents fall back to the KnowledgeAgent.
"""

from __future__ import annotations

from app.agents.base import Agent
from app.agents.catalog import CatalogAgent
from app.agents.handoff import HumanHandoffAgent
from app.agents.knowledge import KnowledgeAgent
from app.agents.rentals import RentalHistoryAgent
from app.agents.subscription import SubscriptionAgent

CATALOG_AGENT = CatalogAgent()
SUBSCRIPTION_AGENT = SubscriptionAgent()
RENTAL_HISTORY_AGENT = RentalHistoryAgent()
KNOWLEDGE_AGENT = KnowledgeAgent()
HUMAN_HANDOFF_AGENT = HumanHandoffAgent()

# intent -> specialist agent
ROUTES: dict[str, Agent] = {
    "catalog_search": CATALOG_AGENT,
    "subscription_question": SUBSCRIPTION_AGENT,
    "rental_history": RENTAL_HISTORY_AGENT,
    "knowledge_question": KNOWLEDGE_AGENT,
    "human_handoff": HUMAN_HANDOFF_AGENT,
}

# Low-confidence / unknown intent falls back here.
FALLBACK: Agent = KNOWLEDGE_AGENT

# All agents by name (for /agents introspection).
AGENTS: dict[str, Agent] = {agent.name: agent for agent in ROUTES.values()}


def route(intent: str) -> Agent:
    """Return the specialist for an intent, or the fallback for an unknown one."""
    return ROUTES.get(intent, FALLBACK)
