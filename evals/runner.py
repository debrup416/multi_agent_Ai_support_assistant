"""Run eval cases through the real pipeline and report pass/fail per case."""

from __future__ import annotations

from typing import Any

from app.config import get_settings
from app.llm import get_llm_client
from app.llm.base import LLMClient
from app.observability import tracing
from app.orchestrator import respond
from app.schemas.contracts import AgentRequest
from evals.cases import CASES, EvalCase


def run_case(case: EvalCase, llm: LLMClient) -> dict[str, Any]:
    """Run one case and return a structured result with per-check booleans."""
    request = AgentRequest(
        customer_id=case.customer_id,
        conversation_id=f"eval-{case.name}",
        message=case.message,
    )
    response = respond(request, llm)
    answer_lower = response.answer.lower()

    checks: dict[str, bool] = {}
    if case.expected_intent is not None:
        checks["intent"] = response.intent == case.expected_intent
    if case.expected_agent is not None:
        checks["agent"] = response.selected_agent == case.expected_agent
    if case.expected_tools is not None:
        if case.expected_tools:
            checks["tools"] = sorted(response.tools_used) == sorted(case.expected_tools)
        else:
            checks["tools"] = response.tools_used == []
    if case.expected_next_action is not None:
        checks["next_action"] = response.next_action == case.expected_next_action
    for term in case.must_include:
        checks[f"includes:{term}"] = term.lower() in answer_lower
    for term in case.must_not_include:
        checks[f"excludes:{term}"] = term.lower() not in answer_lower
    if case.safety_behavior == "answer_with_citation":
        checks["has_citation"] = len(response.citations) > 0

    return {
        "name": case.name,
        "passed": all(checks.values()),
        "checks": checks,
        "selected_agent": response.selected_agent,
        "intent": response.intent,
        "tools_used": response.tools_used,
        "next_action": response.next_action,
        "answer": response.answer,
    }


def run_evals(llm: LLMClient | None = None) -> dict[str, Any]:
    """Run all cases; return per-case results and a summary count."""
    tracing.init_observability(get_settings())
    client = llm or get_llm_client()
    try:
        results = [run_case(case, client) for case in CASES]
    finally:
        # Batch process: flush so the last cases' traces aren't lost on exit.
        tracing.flush()
    passed = sum(1 for r in results if r["passed"])
    return {"total": len(results), "passed": passed, "failed": len(results) - passed, "results": results}
