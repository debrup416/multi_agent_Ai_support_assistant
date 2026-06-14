"""The programmatic seam: run one customer message through the ADK coordinator.

``run_query`` is what both the ``POST /adk/respond`` route and ``python -m adk_agents.demo``
call. It keeps a process-wide ``InMemorySessionService`` keyed by ``conversation_id`` so a
multi-turn conversation accumulates context, injects the (trusted) ``customer_id`` into
session state for the scoped specialists, and returns only what actually happened — the
reply, the responding sub-agent, and the MCP tools that were called.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

from google.adk.agents.run_config import RunConfig, StreamingMode
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from app.config import get_settings
from app.guardrails.output_guard import EXPOSURE_REDACTION, scan_exposure
from app.observability import tracing
from app.tools import REGISTRY

from adk_agents.observability import build_observability_plugin
from adk_agents.pagila_support.agent import root_agent
from adk_agents.pagila_support.specialists import TOOLSETS
from adk_agents.schemas import AdkChatResult

# Wire Langfuse here too, so `python -m adk_agents.demo` (which imports this module
# directly, not via the API factory) gets observability. Idempotent + no-op when off.
tracing.init_observability(get_settings())

# Optional guardrail plugin (needs the `guardrails` extra). One plugin on the Runner
# guards the coordinator and every specialist; absent here, the agents run unguarded.
try:
    from adk_agents.guardrails import build_guardrail_plugin

    _plugins = [p for p in [build_guardrail_plugin(get_settings())] if p is not None]
except ImportError:
    _plugins = []

# Observability plugin (needs the `observability` extra + active config). Opens one Langfuse
# root span per run; absent/off, it simply isn't registered.
_obs_plugin = build_observability_plugin()
if _obs_plugin is not None:
    _plugins.append(_obs_plugin)

_APP_NAME = "pagila-support-adk"
_session_service = InMemorySessionService()
_runner = Runner(
    agent=root_agent,
    app_name=_APP_NAME,
    session_service=_session_service,
    plugins=_plugins,
)


async def _ensure_session(user_id: str, session_id: str, customer_id: int | None) -> None:
    existing = await _session_service.get_session(
        app_name=_APP_NAME, user_id=user_id, session_id=session_id
    )
    if existing is None:
        # Only seed customer_id when present, so the `{customer_id?}` template renders
        # empty (not "None") for anonymous chats and the specialist asks for an id.
        state = {"customer_id": customer_id} if customer_id is not None else {}
        await _session_service.create_session(
            app_name=_APP_NAME, user_id=user_id, session_id=session_id, state=state
        )


async def run_query(
    message: str, customer_id: int | None, conversation_id: str
) -> AdkChatResult:
    """Send one message to the coordinator and collect the final response."""
    user_id = f"customer:{customer_id}" if customer_id is not None else "anonymous"
    session_id = conversation_id
    await _ensure_session(user_id, session_id, customer_id)

    new_message = types.Content(role="user", parts=[types.Part(text=message)])

    reply = ""
    selected_agent: str | None = None
    tools_used: list[str] = []
    async for event in _runner.run_async(
        user_id=user_id, session_id=session_id, new_message=new_message
    ):
        for call in event.get_function_calls():
            # Keep real MCP tool calls; drop ADK control calls like transfer_to_agent.
            if call.name in REGISTRY and call.name not in tools_used:
                tools_used.append(call.name)
        if event.is_final_response() and event.content and event.content.parts:
            text = event.content.parts[0].text
            if text:
                reply = text
                selected_agent = event.author

    return AdkChatResult(
        conversation_id=conversation_id,
        reply=reply,
        selected_agent=selected_agent,
        tools_used=tools_used,
    )


async def stream_query(
    message: str, customer_id: int | None, conversation_id: str
) -> AsyncIterator[str]:
    """Stream the coordinator's reply as NDJSON lines: chunk / blocked / done / error.

    ADK SSE mode yields partial *text* events (deltas) plus a final aggregated event. We
    forward the deltas, validate the accumulated text with the same exposure check the core
    path uses (``scan_exposure``), and cut over to a safe reply (``blocked``) if it trips
    mid-stream. tools_used / selected_agent are collected exactly as in ``run_query``.
    """
    user_id = f"customer:{customer_id}" if customer_id is not None else "anonymous"
    session_id = conversation_id
    await _ensure_session(user_id, session_id, customer_id)
    new_message = types.Content(role="user", parts=[types.Part(text=message)])

    displayed = ""
    reply = ""
    selected_agent: str | None = None
    tools_used: list[str] = []
    blocked = False

    def _ndjson(obj: dict) -> str:
        return json.dumps(obj) + "\n"

    try:
        async for event in _runner.run_async(
            user_id=user_id,
            session_id=session_id,
            new_message=new_message,
            run_config=RunConfig(streaming_mode=StreamingMode.SSE),
        ):
            for call in event.get_function_calls():
                if call.name in REGISTRY and call.name not in tools_used:
                    tools_used.append(call.name)
            if blocked:
                continue  # ponytail: drain remaining events, ignore (don't re-emit leaked text)
            parts = event.content.parts if event.content else None
            if event.partial and parts:
                if any(p.function_call for p in parts):
                    continue  # function-call argument streaming — not user-facing
                delta = "".join(p.text or "" for p in parts)
                if not delta:
                    continue
                displayed += delta
                if scan_exposure(displayed):
                    blocked = True
                    reply = EXPOSURE_REDACTION
                    yield _ndjson({"type": "blocked", "text": EXPOSURE_REDACTION})
                    continue
                yield _ndjson({"type": "chunk", "text": delta})
            elif event.is_final_response() and parts:
                text = "".join(p.text or "" for p in parts if p.text)
                if text:
                    reply = text
                    selected_agent = event.author
    except Exception as exc:  # noqa: BLE001 -- surface mid-stream failures to the client
        yield _ndjson({"type": "error", "detail": str(exc)})
        return

    # No partial text streamed (e.g. an input-guard block/escalate returns one canned
    # message) -> deliver the final reply as a single chunk so the bubble isn't left empty.
    if not blocked and not displayed and reply:
        yield _ndjson({"type": "chunk", "text": reply})

    result = AdkChatResult(
        conversation_id=conversation_id,
        reply=reply or displayed,
        selected_agent=selected_agent,
        tools_used=tools_used,
    )
    yield _ndjson({"type": "done", "response": result.model_dump(mode="json")})


async def aclose() -> None:
    """Close the live MCP sessions held by the specialists (best effort)."""
    for toolset in TOOLSETS:
        try:
            await toolset.close()
        except Exception:  # noqa: BLE001 -- shutdown is best-effort
            pass
    tracing.flush()
