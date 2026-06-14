"""The Langfuse observability seam — the *only* module that imports ``langfuse``.

Posture: fully optional and fully gated. With the ``observability`` extra uninstalled,
the Langfuse keys absent, or ``langfuse_enabled=false``, every public function here is a
no-op and the rest of the codebase behaves byte-for-byte as it did before. Nothing in the
request path may break because of observability, so each span helper also degrades to a
no-op (with a one-time warning) if the Langfuse SDK raises.

How the pieces fit together:

- ``init_observability`` is called once per process at startup. When active it points the
  Langfuse SDK at the server (via env) and constructs the client. We do NOT register a
  LiteLLM langfuse callback — the classic one is incompatible with the Langfuse v4 SDK and the
  OTel one conflicts with this SDK's tracer provider (see ``init_observability``).
- ``root_request_span`` / ``tool_span`` add the request/tool *structure*; ``record_generation``
  emits the LLM call (model, prompt, output, token usage, cost) as a GENERATION observation —
  this is how token/cost reaches Langfuse, on the single SDK tracer provider. All of it
  correlates on the ``conversation_id``, set as the Langfuse ``session_id`` on the root span.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from typing import Any

from app.config import Settings, get_settings
from app.observability.logging import get_logger

_logger = get_logger("observability.tracing")

# The optional dependency. Absence is a clean no-op, never an error.
# NB: in the Langfuse v4 SDK, `propagate_attributes` is a module-level context manager (it
# sets trace-level session_id/user_id/tags on the current OTel context), NOT a client method.
try:
    from langfuse import Langfuse, get_client, propagate_attributes

    _LANGFUSE_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without the extra
    Langfuse = None  # type: ignore[assignment, misc]
    get_client = None  # type: ignore[assignment]
    propagate_attributes = None  # type: ignore[assignment]
    _LANGFUSE_AVAILABLE = False

_initialized = False
_client: Any = None
_warned: set[str] = set()


def _warn_once(message: str, exc: Exception) -> None:
    """Log a Langfuse failure once per message so a misconfig can't spam the logs."""
    if message in _warned:
        return
    _warned.add(message)
    _logger.warning("%s: %s: %s", message, type(exc).__name__, exc)


def is_active() -> bool:
    """True only when the SDK is importable AND config enables it with both keys."""
    if not _LANGFUSE_AVAILABLE:
        return False
    try:
        return get_settings().observability_active
    except Exception:  # noqa: BLE001 - never let a config error break a request
        return False


def _capture_io() -> bool:
    try:
        return get_settings().langfuse_capture_io
    except Exception:  # noqa: BLE001
        return False


def init_observability(settings: Settings | None = None) -> None:
    """Idempotently wire Langfuse + the LiteLLM callback. Safe no-op when inactive.

    Call once per process at each entrypoint (API, MCP, ADK/SK runners, evals). When
    inactive it returns immediately, so guarding the call site is unnecessary.
    """
    global _initialized, _client
    if _initialized:
        return
    settings = settings or get_settings()
    if not (_LANGFUSE_AVAILABLE and settings.observability_active):
        _initialized = True  # remember we checked; stays a no-op for the process
        return
    try:
        # LiteLLM's "langfuse" callback and the SDK both read these from the env.
        os.environ["LANGFUSE_PUBLIC_KEY"] = settings.langfuse_public_key.get_secret_value()
        os.environ["LANGFUSE_SECRET_KEY"] = settings.langfuse_secret_key.get_secret_value()
        os.environ["LANGFUSE_HOST"] = settings.langfuse_host

        # NB: we deliberately do NOT register a LiteLLM langfuse callback. The classic
        # "langfuse" callback expects the v2 SDK (`langfuse.version`) and raises on v4; the
        # "langfuse_otel" callback sets up a second OTel tracer provider that conflicts with
        # this SDK's, producing empty spans (no model/usage/cost). Instead we emit GENERATION
        # observations ourselves via `record_generation` (below) on the single SDK provider —
        # so token/cost is captured reliably for the paths that use our own LLM client.
        _client = Langfuse(
            public_key=settings.langfuse_public_key.get_secret_value(),
            secret_key=settings.langfuse_secret_key.get_secret_value(),
            host=settings.langfuse_host,
        )
        _logger.info(
            "observability_initialized",
            extra={"event": {"host": settings.langfuse_host, "capture_io": settings.langfuse_capture_io}},
        )
    except Exception as exc:  # noqa: BLE001 - degrade to no-op, never crash startup
        _warn_once("init_observability failed", exc)
        _client = None
    finally:
        _initialized = True


def _resolve_client() -> Any:
    if _client is not None:
        return _client
    if get_client is not None:
        return get_client()
    return None


class _NoopSpan:
    """The handle yielded when tracing is inactive or the SDK errors."""

    def update(self, **_: Any) -> None:  # noqa: D401 - intentional no-op
        pass


class _Span:
    """Thin wrapper over a Langfuse observation; all updates are best-effort."""

    def __init__(self, observation: Any) -> None:
        self._obs = observation

    def update(
        self,
        *,
        output: Any | None = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
        status_message: str | None = None,
    ) -> None:
        try:
            kwargs: dict[str, Any] = {}
            if output is not None and _capture_io():
                kwargs["output"] = output
            if metadata is not None:
                kwargs["metadata"] = metadata
            if level is not None:
                kwargs["level"] = level
            if status_message is not None:
                kwargs["status_message"] = status_message
            if kwargs:
                self._obs.update(**kwargs)
        except Exception as exc:  # noqa: BLE001
            _warn_once("span.update failed", exc)


_NOOP = _NoopSpan()


@contextmanager
def root_request_span(
    *,
    name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    input: Any | None = None,
) -> Iterator[_NoopSpan | _Span]:
    """Open the per-request root span and propagate trace-level attributes.

    ``session_id``/``user_id``/``tags`` are pushed onto every child observation —
    including the generations LiteLLM emits inside this block — so the whole turn shows
    up as one correlated trace. Yields a span handle (no-op when inactive); the body
    always runs exactly once regardless of SDK errors.
    """
    if not is_active():
        yield _NOOP
        return

    handle: _NoopSpan | _Span = _NOOP
    stack: ExitStack | None = None
    try:
        client = _resolve_client()
        if client is None:
            raise RuntimeError("Langfuse client unavailable")
        stack = ExitStack()
        stack.enter_context(
            propagate_attributes(session_id=session_id, user_id=user_id, tags=tags)
        )
        observation = stack.enter_context(
            client.start_as_current_observation(
                as_type="span",
                name=name,
                input=input if _capture_io() else None,
            )
        )
        handle = _Span(observation)
    except Exception as exc:  # noqa: BLE001
        _warn_once("root_request_span setup failed", exc)
        if stack is not None:
            stack.close()
            stack = None

    try:
        yield handle
    finally:
        if stack is not None:
            try:
                stack.close()
            except Exception as exc:  # noqa: BLE001
                _warn_once("root_request_span teardown failed", exc)


@contextmanager
def tool_span(*, name: str, input: Any | None = None) -> Iterator[_NoopSpan | _Span]:
    """Open a ``tool:<name>`` span around a single tool invocation.

    Nests under whatever observation is current (the orchestrator root span for the core
    path). No-op when inactive; never raises into the tool call.
    """
    if not is_active():
        yield _NOOP
        return

    handle: _NoopSpan | _Span = _NOOP
    stack: ExitStack | None = None
    try:
        client = _resolve_client()
        if client is None:
            raise RuntimeError("Langfuse client unavailable")
        stack = ExitStack()
        observation = stack.enter_context(
            client.start_as_current_observation(
                as_type="span",
                name=f"tool:{name}",
                input=input if _capture_io() else None,
            )
        )
        handle = _Span(observation)
    except Exception as exc:  # noqa: BLE001
        _warn_once("tool_span setup failed", exc)
        if stack is not None:
            stack.close()
            stack = None

    try:
        yield handle
    finally:
        if stack is not None:
            try:
                stack.close()
            except Exception as exc:  # noqa: BLE001
                _warn_once("tool_span teardown failed", exc)


class _DetachedSpan:
    """A span whose start and end live in different callbacks (e.g. ADK before/after_run).

    Holds the ``ExitStack`` open between ``begin_span`` and ``end()``; both ``update`` and
    ``end`` are best-effort and never raise into the caller.
    """

    def __init__(self, span: _Span, stack: ExitStack) -> None:
        self._span = span
        self._stack = stack

    def update(self, **kwargs: Any) -> None:
        self._span.update(**kwargs)

    def end(self) -> None:
        try:
            self._stack.close()
        except Exception as exc:  # noqa: BLE001
            _warn_once("detached span end failed", exc)


def begin_span(
    *,
    name: str,
    session_id: str | None = None,
    user_id: str | None = None,
    tags: list[str] | None = None,
    input: Any | None = None,
) -> _DetachedSpan | None:
    """Imperatively open a root span for frameworks whose start/end are separate callbacks.

    Returns ``None`` when inactive (callers null-check). Pair with ``handle.end()``. Used by
    the ADK observability plugin (``before_run_callback`` opens, ``after_run_callback`` ends).
    """
    if not is_active():
        return None
    try:
        client = _resolve_client()
        if client is None:
            raise RuntimeError("Langfuse client unavailable")
        stack = ExitStack()
        stack.enter_context(
            propagate_attributes(session_id=session_id, user_id=user_id, tags=tags)
        )
        observation = stack.enter_context(
            client.start_as_current_observation(
                as_type="span",
                name=name,
                input=input if _capture_io() else None,
            )
        )
        return _DetachedSpan(_Span(observation), stack)
    except Exception as exc:  # noqa: BLE001
        _warn_once("begin_span failed", exc)
        return None


def record_generation(
    *,
    name: str,
    model: str | None = None,
    input: Any | None = None,
    output: Any | None = None,
    prompt_tokens: int | None = None,
    completion_tokens: int | None = None,
    total_tokens: int | None = None,
    cost_usd: float | None = None,
) -> None:
    """Emit one Langfuse GENERATION observation with model + token usage + cost.

    Call right after an LLM response, from a runtime's own LLM client. It nests under the
    current span (the orchestrator/SK root span), so the generation appears inside the turn's
    trace. No-op when inactive; never raises into the caller. This is how token/cost actually
    reaches Langfuse — we do not rely on LiteLLM's langfuse callback (incompatible with v4).
    """
    if not is_active():
        return
    try:
        client = _resolve_client()
        if client is None:
            raise RuntimeError("Langfuse client unavailable")
        usage_details: dict[str, int] = {}
        if prompt_tokens is not None:
            usage_details["input"] = prompt_tokens
        if completion_tokens is not None:
            usage_details["output"] = completion_tokens
        if total_tokens is not None:
            usage_details["total"] = total_tokens
        with client.start_as_current_observation(
            as_type="generation",
            name=name,
            model=model,
            input=input if _capture_io() else None,
        ) as gen:
            kwargs: dict[str, Any] = {}
            if output is not None and _capture_io():
                kwargs["output"] = output
            if usage_details:
                kwargs["usage_details"] = usage_details
            if cost_usd is not None:
                kwargs["cost_details"] = {"total": cost_usd}
            if kwargs:
                gen.update(**kwargs)
    except Exception as exc:  # noqa: BLE001
        _warn_once("record_generation failed", exc)


def flush() -> None:
    """Flush pending events. Call before a short-lived process exits (evals, MCP stdio)."""
    if not is_active():
        return
    try:
        client = _resolve_client()
        if client is not None:
            client.flush()
    except Exception as exc:  # noqa: BLE001
        _warn_once("flush failed", exc)


def shutdown() -> None:
    """Flush and stop the background exporter (graceful process shutdown)."""
    if not is_active():
        return
    try:
        client = _resolve_client()
        if client is not None:
            client.shutdown()
    except Exception as exc:  # noqa: BLE001
        _warn_once("shutdown failed", exc)
