"""Langfuse observability for the ADK runtime — one ADK plugin on the Runner.

This is the ADK-side counterpart to the core orchestrator's root request span. Token and
cost capture is **automatic** for ADK: its model calls go through LiteLLM, and the global
``"langfuse"`` callback registered by ``app.observability.tracing.init_observability`` emits
each generation (model, prompt, usage, cost). This plugin only adds the per-run *structure*
and correlation:

- ``before_run_callback`` (once per turn) binds the ``conversation_id`` for log correlation
  and opens a root span; the generations LiteLLM emits during the run group under it.
- ``after_run_callback`` ends that span.

Everything is gated behind ``tracing.is_active()`` and wrapped defensively, so when
observability is off (or the SDK errors) the plugin is an inert no-op and never affects a run.
"""

from __future__ import annotations

from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types

from app.observability import tracing
from app.observability.logging import set_conversation_id


def _text_of(content: types.Content | None) -> str:
    if content is None:
        return ""
    return "".join(p.text or "" for p in (content.parts or []) if hasattr(p, "text"))


class ObservabilityPlugin(BasePlugin):
    """Opens one Langfuse root span per ADK run, keyed by invocation id."""

    def __init__(self) -> None:
        super().__init__(name="observability")
        # Keyed by invocation_id so concurrent runs don't clobber each other's span.
        self._spans: dict[str, object] = {}

    async def before_run_callback(self, *, invocation_context):  # noqa: ANN001
        session = getattr(invocation_context, "session", None)
        session_id = getattr(session, "id", None)
        user_id = getattr(session, "user_id", None)
        # Correlate this process's structured logs with the conversation.
        set_conversation_id(session_id)
        handle = tracing.begin_span(
            name="adk.run",
            session_id=session_id,
            user_id=user_id,
            tags=["adk"],
            input=_text_of(getattr(invocation_context, "user_content", None)),
        )
        if handle is not None:
            self._spans[invocation_context.invocation_id] = handle
        return None

    async def after_run_callback(self, *, invocation_context):  # noqa: ANN001
        handle = self._spans.pop(getattr(invocation_context, "invocation_id", None), None)
        if handle is not None:
            handle.end()
        return None


def build_observability_plugin() -> ObservabilityPlugin | None:
    """Construct the plugin, or None when observability is inactive (so it isn't registered)."""
    if not tracing.is_active():
        return None
    return ObservabilityPlugin()
