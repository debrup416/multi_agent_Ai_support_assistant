"""Observability seam tests.

The headline guarantee: when observability is inactive (the default, and the state of
the test suite — no Langfuse keys, extra may be uninstalled), every ``tracing`` helper is
a no-op that never raises. A second set of tests uses a *fake* Langfuse client (so they run
without the ``observability`` extra) to prove that, when active, the span context managers
and ``record_generation`` drive the SDK client.
"""

from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import litellm
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.observability import tracing


@pytest.fixture(autouse=True)
def _reset_tracing_state():
    """Reset the module-level singleton/init flags around every test."""
    saved = (tracing._initialized, tracing._client, set(tracing._warned))
    tracing._initialized = False
    tracing._client = None
    tracing._warned.clear()
    yield
    tracing._initialized, tracing._client, _warned = saved
    tracing._warned.clear()
    tracing._warned.update(_warned)


# --- The no-op contract (must hold whether or not langfuse is installed) -------------


def test_inactive_helpers_are_noops(monkeypatch):
    # Force the inactive path deterministically, independent of the dev env's .env.
    monkeypatch.setattr(tracing, "_LANGFUSE_AVAILABLE", False)

    assert tracing.is_active() is False

    # Context managers yield a usable handle and never raise on update.
    with tracing.root_request_span(name="agent.respond", session_id="c1", input="hi") as span:
        span.update(output="bye", metadata={"intent": "x"})
    with tracing.tool_span(name="search_kb", input={"q": 1}) as span:
        span.update(output={"r": 2}, metadata={"status": "ok"}, level="DEFAULT")
    assert tracing.begin_span(name="adk.run") is None

    # init / record_generation / flush / shutdown are safe no-ops that never raise.
    tracing.init_observability()
    tracing.record_generation(name="core.complete", model="m", prompt_tokens=1, cost_usd=0.0)
    tracing.flush()
    tracing.shutdown()


def test_observability_active_predicate():
    # `_env_file=None` so the dev/CI .env (which may enable Langfuse) can't leak keys in.
    base = {"langfuse_public_key": "pk", "langfuse_secret_key": "sk"}
    assert Settings(_env_file=None, langfuse_enabled=False, **base).observability_active is False
    assert (
        Settings(
            _env_file=None, langfuse_enabled=True, langfuse_public_key=None, langfuse_secret_key=None
        ).observability_active
        is False
    )
    assert Settings(_env_file=None, langfuse_enabled=True, **base).observability_active is True


# --- The active path, exercised with a fake Langfuse client --------------------------


class _FakeObservation:
    def __init__(self):
        self.updates: list[dict] = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


class _FakeClient:
    def __init__(self):
        self.observations: list[_FakeObservation] = []
        # `propagate_attributes` is a module-level function in the Langfuse v4 SDK (not a
        # client method); calls land in this list via the patched module function.
        self.propagated: list[dict] = []
        self.flushed = False

    @contextmanager
    def start_as_current_observation(self, **kwargs):
        obs = _FakeObservation()
        obs.created_with = kwargs
        self.observations.append(obs)
        yield obs

    def flush(self):
        self.flushed = True

    def shutdown(self):
        self.flushed = True


def _activate(monkeypatch) -> _FakeClient:
    """Make the seam think Langfuse is installed + configured, backed by a fake client."""
    fake = _FakeClient()
    settings = SimpleNamespace(
        observability_active=True,
        langfuse_capture_io=True,
        langfuse_host="http://localhost:3000",
        langfuse_public_key=SecretStr("pk"),
        langfuse_secret_key=SecretStr("sk"),
    )

    @contextmanager
    def _fake_propagate(**kwargs):
        fake.propagated.append(kwargs)
        yield

    monkeypatch.setattr(tracing, "_LANGFUSE_AVAILABLE", True)
    monkeypatch.setattr(tracing, "Langfuse", lambda **_: fake)
    monkeypatch.setattr(tracing, "get_client", lambda: fake)
    monkeypatch.setattr(tracing, "propagate_attributes", _fake_propagate)
    monkeypatch.setattr(tracing, "get_settings", lambda: settings)
    return fake


def test_init_does_not_register_litellm_callback(monkeypatch):
    # We emit generations via the SDK ourselves; the LiteLLM langfuse callback is NOT used
    # (incompatible with v4 / conflicts with the SDK tracer provider).
    fake = _activate(monkeypatch)
    monkeypatch.setattr(litellm, "success_callback", [])
    monkeypatch.setattr(litellm, "failure_callback", [])

    tracing.init_observability()

    assert "langfuse" not in litellm.success_callback
    assert "langfuse_otel" not in litellm.success_callback
    assert tracing._client is fake  # the SDK client was constructed


def test_active_spans_drive_the_client(monkeypatch):
    fake = _activate(monkeypatch)
    assert tracing.is_active() is True

    with tracing.root_request_span(
        name="agent.respond", session_id="conv-1", user_id="customer:7", tags=["core"], input="hello"
    ) as span:
        span.update(output="hi there", metadata={"intent": "catalog_search"})

    # propagate_attributes received the trace-level attributes; a span was created + updated.
    assert fake.propagated and fake.propagated[0]["session_id"] == "conv-1"
    assert fake.observations[0].created_with["name"] == "agent.respond"
    assert fake.observations[0].updates[0]["output"] == "hi there"

    tracing.flush()
    assert fake.flushed is True


def test_record_generation_emits_usage_and_cost(monkeypatch):
    fake = _activate(monkeypatch)

    tracing.record_generation(
        name="core.complete",
        model="anthropic/claude-haiku-4-5",
        input=[{"role": "user", "content": "hi"}],
        output="hello",
        prompt_tokens=115,
        completion_tokens=62,
        total_tokens=177,
        cost_usd=0.000425,
    )

    gen = fake.observations[-1]
    assert gen.created_with["as_type"] == "generation"
    assert gen.created_with["model"] == "anthropic/claude-haiku-4-5"
    update = gen.updates[-1]
    assert update["usage_details"] == {"input": 115, "output": 62, "total": 177}
    assert update["cost_details"] == {"total": 0.000425}
    assert update["output"] == "hello"
