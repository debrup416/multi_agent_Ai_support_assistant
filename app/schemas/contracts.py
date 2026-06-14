"""The API contract and the internal agent/triage contracts.

``AgentResponse`` is the system's stability promise: FastAPI validates the request
and serializes the response, and the output guardrail validates it once more before
return.
"""

from __future__ import annotations

from typing import Literal, get_args

from pydantic import BaseModel, Field

# The closed set of intents the triage classifier may produce. Keep this in lockstep
# with the routing registry (`app.agents.registry.ROUTES`).
Intent = Literal[
    "catalog_search",
    "subscription_question",
    "rental_history",
    "knowledge_question",
    "human_handoff",
]
INTENTS: tuple[str, ...] = get_args(Intent)

NextAction = Literal["answer", "clarify", "escalate", "handoff", "block"]


class AgentRequest(BaseModel):
    """Inbound request to ``POST /agent/respond``."""

    customer_id: int | None = Field(
        default=None,
        description="Trusted customer id (simplified auth). Null is handled gracefully.",
    )
    conversation_id: str = Field(min_length=1, max_length=128)
    message: str = Field(min_length=1, max_length=4000)


class Citation(BaseModel):
    """A source reference backing part of an answer."""

    source: str  # KB article id / file / tool name
    snippet: str | None = None


class GuardrailResult(BaseModel):
    """Outcome of the output-guardrail review stage."""

    status: Literal["pass", "modified", "blocked"]
    checks: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class AgentResponse(BaseModel):
    """The validated, stable JSON contract returned to the client."""

    conversation_id: str
    intent: str
    selected_agent: str
    answer: str
    confidence: float = Field(ge=0.0, le=1.0)
    tools_used: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    next_action: NextAction
    guardrail_result: GuardrailResult


class TriageDecision(BaseModel):
    """Structured output of the TriageAgent classifier."""

    intent: Intent
    selected_agent: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = Field(default="", max_length=500)


class CatalogSearchTerm(BaseModel):
    """Structured output: the title/keyword the CatalogAgent should search the catalog for.

    Lets the model turn a natural-language question ("any movies about dinosaurs?") into the
    actual title keyword ("dinosaur"), matching how the ADK/SK runtimes pick the tool argument.
    """

    term: str = Field(max_length=100)


class AgentContext(BaseModel):
    """Everything a specialist needs to do its job."""

    request: AgentRequest
    intent: str
    confidence: float
    scratch: dict = Field(default_factory=dict)


class AgentResult(BaseModel):
    """What a specialist returns to the orchestrator."""

    answer: str
    tools_used: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    next_action: NextAction = "answer"
