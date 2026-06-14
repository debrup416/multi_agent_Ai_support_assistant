"""The orchestrator: input guardrail -> triage -> route -> specialist -> output guardrail.

It owns the response build and is the only place that decides ``next_action`` and
assembles the stable ``AgentResponse``. Routing is deterministic; the LLM is used only
inside triage and (grounded) specialist answering.
"""

from __future__ import annotations

from app.agents import route, triage
from app.agents.registry import FALLBACK, HUMAN_HANDOFF_AGENT
from app.config import get_settings
from app.guardrails import review_output, screen_input
from app.llm.base import LLMClient, StructuredOutputError
from app.observability import tracing
from app.observability.logging import get_logger, log_event, set_conversation_id
from app.schemas.contracts import (
    AgentContext,
    AgentRequest,
    AgentResponse,
    GuardrailResult,
)

_logger = get_logger("orchestrator")


def respond(request: AgentRequest, llm: LLMClient) -> AgentResponse:
    """Run the full pipeline and return a validated, guardrailed response."""
    set_conversation_id(request.conversation_id)
    settings = get_settings()

    # The per-request root trace. session_id=conversation_id ties together logs, this span,
    # the triage/specialist generations LiteLLM emits inside, and the tool spans. No-op when
    # observability is off.
    user_id = (
        f"customer:{request.customer_id}" if request.customer_id is not None else "anonymous"
    )
    with tracing.root_request_span(
        name="agent.respond",
        session_id=request.conversation_id,
        user_id=user_id,
        tags=["core"],
        input=request.message,
    ) as span:
        # 1) Input guardrail (deterministic, before any routing or tool use).
        verdict = screen_input(request.message)

        if verdict.action == "block":
            log_event(_logger, "input_guardrail_block", reasons=verdict.reasons)
            span.update(
                output=verdict.canned_answer or "",
                metadata={"intent": "blocked", "selected_agent": "InputGuardrail", "next_action": "block"},
            )
            return AgentResponse(
                conversation_id=request.conversation_id,
                intent="blocked",
                selected_agent="InputGuardrail",
                answer=verdict.canned_answer or "",
                confidence=1.0,
                tools_used=[],
                citations=[],
                next_action="block",
                guardrail_result=GuardrailResult(
                    status="blocked", checks=verdict.checks, reasons=verdict.reasons
                ),
            )

        # 2) Decide intent + agent.
        fallback_used = False
        if verdict.action == "handoff":
            # Sensitive mutation: skip triage, force escalation. No state is ever changed.
            intent, confidence, reason = "human_handoff", 1.0, "sensitive_mutation"
            agent = HUMAN_HANDOFF_AGENT
            scratch = {"handoff_reason": verdict.handoff_reason}
        else:
            scratch = {}
            try:
                decision = triage(
                    AgentContext(request=request, intent="", confidence=0.0), llm
                )
                intent, confidence, reason = decision.intent, decision.confidence, decision.reason
            except StructuredOutputError as exc:
                # Fail closed: treat as low-confidence and clarify via the fallback agent.
                log_event(_logger, "triage_failed", error=str(exc))
                intent, confidence, reason = "knowledge_question", 0.0, "triage_failed"

            if confidence < settings.confidence_threshold:
                fallback_used = True
                agent = FALLBACK
            else:
                agent = route(intent)

        log_event(
            _logger,
            "routing_decision",
            intent=intent,
            selected_agent=agent.name,
            confidence=confidence,
            reason=reason,
            fallback=fallback_used,
        )
        span.update(
            metadata={
                "intent": intent,
                "selected_agent": agent.name,
                "confidence": confidence,
                "fallback": fallback_used,
            }
        )

        # 3) Run the specialist.
        ctx = AgentContext(
            request=request, intent=intent, confidence=confidence, scratch=scratch
        )
        result = agent.handle(ctx, llm)

        next_action = "clarify" if fallback_used else result.next_action

        # 4) Output guardrail over the draft answer.
        guard, final_answer = review_output(
            answer=result.answer,
            intent=intent,
            tools_used=result.tools_used,
            citations=result.citations,
            next_action=next_action,
        )
        if guard.status == "blocked":
            next_action = "block"
        log_event(
            _logger,
            "guardrail_result",
            status=guard.status,
            checks=guard.checks,
            reasons=guard.reasons,
        )
        span.update(
            output=final_answer,
            metadata={"next_action": next_action, "guardrail_status": guard.status},
        )

        return AgentResponse(
            conversation_id=request.conversation_id,
            intent=intent,
            selected_agent=agent.name,
            answer=final_answer,
            confidence=confidence,
            tools_used=result.tools_used,
            citations=result.citations,
            next_action=next_action,
            guardrail_result=guard,
        )
