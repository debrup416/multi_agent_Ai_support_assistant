"""Output guardrails — run over the draft answer before it is returned.

Deterministic checks (an LLM tone reviewer is a clean seam but not required):
- schema: guaranteed by constructing the Pydantic ``AgentResponse``;
- data exposure: the answer must not leak the system prompt or internal identifiers;
- grounding: data-backed intents must show tool evidence; KB answers cite or say none.
The verdict is surfaced to the caller in ``guardrail_result``.
"""

from __future__ import annotations

import re

from app.schemas.contracts import Citation, GuardrailResult

_DATA_INTENTS = {"catalog_search", "subscription_question", "rental_history"}
_EXPOSURE = re.compile(r"system\s+prompt|you are the .{0,40}specialist|TRIAGE_SYSTEM", re.I)

_CHECKS = ["schema", "data_exposure", "grounding", "tone"]

_SAFE_FALLBACK = (
    "I'm sorry, I couldn't verify that from our systems just now. "
    "Please try again or ask me something else."
)

# Reused by the streaming path (app/orchestrator/streaming.py) to validate each chunk.
EXPOSURE_REDACTION = (
    "I'm not able to share internal details, but I'm happy to help with your "
    "request — could you rephrase what you need?"
)


def scan_exposure(text: str) -> bool:
    """True if the text leaks the system prompt or an internal identifier."""
    return bool(_EXPOSURE.search(text))


def review_output(
    *,
    answer: str,
    intent: str,
    tools_used: list[str],
    citations: list[Citation],
    next_action: str,
) -> tuple[GuardrailResult, str]:
    """Return the guardrail verdict and a (possibly replaced) safe answer."""
    reasons: list[str] = []
    status = "pass"
    out = answer

    # Data-exposure: never echo the system prompt or internal identifiers.
    if scan_exposure(answer):
        status = "modified"
        reasons.append("redacted_potential_prompt_or_internal_exposure")
        out = EXPOSURE_REDACTION

    # Grounding: when an answer asserts data-backed facts, it must show tool evidence.
    # Skipped for clarify/escalate/handoff/block responses, which legitimately have none.
    if next_action == "answer" and intent in _DATA_INTENTS and not tools_used:
        status = "blocked"
        reasons.append("data_backed_answer_missing_tool_evidence")
        out = _SAFE_FALLBACK

    return GuardrailResult(status=status, checks=_CHECKS, reasons=reasons), out
