"""The tool adapter seam + per-call structured logging.

``invoke`` is the single choke point through which agents and REST routes call a
tool. Today it runs the tool **in-process**; the same signature could front an MCP
client instead, with no change to agent code. Every call logs ``conversation_id``,
``tool``, ``status`` (ok/empty/error), ``latency_ms``, and ``error`` when applicable.
"""

from __future__ import annotations

import time

from pydantic import BaseModel

from app.observability import tracing
from app.observability.logging import get_logger, log_event
from app.tools.descriptors import ToolSpec

_logger = get_logger("tools")


def invoke(spec: ToolSpec, payload: BaseModel | dict) -> BaseModel:
    """Validate input, run the tool, log the call, return the typed output."""
    inp = (
        payload
        if isinstance(payload, spec.input_model)
        else spec.input_model.model_validate(payload)
    )
    start = time.perf_counter()
    status = "ok"
    error: str | None = None
    result: BaseModel | None = None
    # One span per tool call, covering every transport (agents, REST, MCP). No-op when off.
    with tracing.tool_span(name=spec.name, input=inp.model_dump(mode="json")) as span:
        try:
            result = spec.func(inp)
            if spec.is_empty is not None and spec.is_empty(result):
                status = "empty"
            return result
        except Exception as exc:  # noqa: BLE001 — log then re-raise for the caller to handle
            status = "error"
            error = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            latency_ms = round((time.perf_counter() - start) * 1000, 1)
            log_event(
                _logger,
                "tool_call",
                tool=spec.name,
                status=status,
                latency_ms=latency_ms,
                error=error,
            )
            span.update(
                output=result.model_dump(mode="json") if result is not None else None,
                metadata={"status": status, "latency_ms": latency_ms},
                level="ERROR" if status == "error" else "DEFAULT",
                status_message=error,
            )
