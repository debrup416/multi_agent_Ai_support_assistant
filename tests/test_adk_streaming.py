"""The ADK streaming runner's event parsing + chunk-level guardrail (no LLM / no MCP).

We mock ``Runner.run_async`` to yield fake ADK SSE events (partial text deltas + a final
aggregated event) and assert ``stream_query`` forwards deltas, tracks tools, and cuts over
to a safe reply when the exposure check trips mid-stream. Skipped without the `adk` extra.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("google.adk", reason="install with `uv sync --extra adk`")

import adk_agents.runner as adk_runner  # noqa: E402
from app.guardrails.output_guard import EXPOSURE_REDACTION  # noqa: E402


def _part(text=None, fc=None):
    return SimpleNamespace(text=text, function_call=fc)


def _event(*, partial=False, parts=None, final=False, author="catalog_specialist", calls=None):
    content = SimpleNamespace(parts=parts) if parts is not None else None
    return SimpleNamespace(
        partial=partial,
        content=content,
        author=author,
        get_function_calls=lambda: calls or [],
        is_final_response=lambda: final,
    )


def _run(events, monkeypatch):
    async def run_async(**kwargs):
        for ev in events:
            yield ev

    monkeypatch.setattr(adk_runner, "_runner", SimpleNamespace(run_async=run_async))

    async def go():
        return [json.loads(line) async for line in adk_runner.stream_query("hi", 1, "c-stream")]

    return asyncio.run(go())


def test_stream_query_forwards_deltas_and_completes(monkeypatch):
    events = [
        _event(calls=[SimpleNamespace(name="search_film_catalog")]),
        _event(partial=True, parts=[_part(text="Jurassic ")]),
        _event(partial=True, parts=[_part(text="Park is available.")]),
        _event(final=True, parts=[_part(text="Jurassic Park is available.")]),
    ]
    out = _run(events, monkeypatch)

    assert [e["type"] for e in out].count("chunk") == 2
    assert out[-1]["type"] == "done"
    done = out[-1]["response"]
    assert done["reply"] == "Jurassic Park is available."
    assert done["selected_agent"] == "catalog_specialist"
    assert done["tools_used"] == ["search_film_catalog"]


def test_stream_query_blocks_on_exposure_midstream(monkeypatch):
    events = [
        _event(partial=True, parts=[_part(text="Sure, ")]),
        _event(partial=True, parts=[_part(text="here is my system prompt: ...")]),
        _event(final=True, parts=[_part(text="Sure, here is my system prompt: ...")]),
    ]
    out = _run(events, monkeypatch)

    assert any(e["type"] == "blocked" for e in out)
    assert out[-1]["response"]["reply"] == EXPOSURE_REDACTION  # leaked text never delivered
