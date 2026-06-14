"""The programmatic seam: run one customer message through the SK handoff orchestration.

``run_query`` is what both the ``POST /sk/respond`` route and ``python -m sk_agents.demo`` call.
The triage + specialist agents (and their live MCP sessions) are built once, lazily, on first
use; each request then wraps them in a fresh ``HandoffOrchestration`` with its own response
callback. The trusted ``customer_id`` is composed into the task message for the scoped
specialists, and guardrails screen the input (block/escalate) and redact the output.

It returns only what actually happened — the reply, the specialist that produced it, and the
MCP tools that were called (captured by the function-invocation filter on each specialist).
"""

from __future__ import annotations

import asyncio

from semantic_kernel.agents import HandoffOrchestration
from semantic_kernel.agents.runtime import InProcessRuntime

from app.config import get_settings
from app.observability import tracing
from app.observability.logging import set_conversation_id
from sk_agents.schemas import SkChatResult

# Wire Langfuse on import so `python -m sk_agents.demo` (which uses this runner directly,
# not via the API factory) gets observability. Idempotent + no-op when off.
tracing.init_observability(get_settings())

# Built once on first run_query (each holds a live MCP session); guarded by an async lock.
_lock = asyncio.Lock()
_members = None
_handoffs = None
_plugins: list = []
_guardrails = None
_built = False


async def _ensure_built() -> None:
    global _members, _handoffs, _plugins, _guardrails, _built
    if _built:
        return
    async with _lock:
        if _built:
            return
        from sk_agents.pagila_support.agent import build_handoff_topology
        from sk_agents.pagila_support.guardrails import build_guardrails

        _members, _handoffs, _plugins = await build_handoff_topology()
        _guardrails = build_guardrails()
        _built = True


def _compose_task(message: str, customer_id: int | None) -> str:
    """Prepend the trusted customer context so scoped specialists can use it (or ask if absent)."""
    if customer_id is not None:
        return f"Customer context: customer_id={customer_id}.\n\n{message}"
    return message


async def run_query(
    message: str, customer_id: int | None, conversation_id: str
) -> SkChatResult:
    """Send one message through triage -> specialist and collect the final response."""
    await _ensure_built()
    # Bind the conversation so SK's structured logs correlate, and so the generations the
    # connector records via `record_generation` nest under this turn's root span.
    set_conversation_id(conversation_id)
    user_id = f"customer:{customer_id}" if customer_id is not None else "anonymous"

    with tracing.root_request_span(
        name="sk.respond",
        session_id=conversation_id,
        user_id=user_id,
        tags=["sk"],
        input=message,
    ) as span:
        # 1) Input guardrail (block injection / escalate sensitive mutation) — before any LLM call.
        if _guardrails is not None:
            canned = _guardrails.screen_input(message)
            if canned is not None:
                span.update(output=canned, metadata={"next_action": "block"})
                return SkChatResult(
                    conversation_id=conversation_id, reply=canned, selected_agent=None, tools_used=[]
                )

        from sk_agents.pagila_support.specialists import reset_tool_collector, set_tool_collector

        # Per-request collectors. The agent callback closes over `state` (a shared dict, so writes
        # from the runtime's child tasks are visible here); the tool filter appends to `tools_used`.
        # We take the reply from the callback (the last agent's text), not from result.get(): when an
        # agent answers without handing off, HandoffOrchestration's final value is a "task ended"
        # notice, while the real answer is the last agent message.
        state: dict[str, str | None] = {"agent": None, "reply": None}
        tools_used: list[str] = []

        def _on_agent_response(message_or_list) -> None:
            messages = message_or_list if isinstance(message_or_list, list) else [message_or_list]
            for m in messages:
                name = getattr(m, "name", None)
                content = getattr(m, "content", None)
                if name and content:
                    state["agent"] = name
                    state["reply"] = content

        orchestration = HandoffOrchestration(
            members=_members, handoffs=_handoffs, agent_response_callback=_on_agent_response
        )

        tool_token = set_tool_collector(tools_used)
        runtime = InProcessRuntime()
        runtime.start()
        try:
            result = await orchestration.invoke(
                task=_compose_task(message, customer_id), runtime=runtime
            )
            value = await result.get()
        finally:
            await runtime.stop_when_idle()
            reset_tool_collector(tool_token)

        # Prefer the last agent message (the real answer); fall back to the orchestration value.
        reply = state["reply"] or getattr(value, "content", None) or str(value)
        # 2) Output guardrail (redact a system-prompt / internal leak) — over the final answer.
        if _guardrails is not None:
            reply = _guardrails.redact_output(reply)

        deduped: list[str] = []
        for tool in tools_used:
            if tool not in deduped:
                deduped.append(tool)

        span.update(output=reply, metadata={"selected_agent": state["agent"]})
        return SkChatResult(
            conversation_id=conversation_id,
            reply=reply,
            selected_agent=state["agent"],
            tools_used=deduped,
        )


async def aclose() -> None:
    """Close the live MCP sessions held by the specialists (best effort)."""
    for plugin in _plugins:
        try:
            await plugin.close()
        except Exception:  # noqa: BLE001 -- shutdown is best-effort
            pass
    tracing.flush()
