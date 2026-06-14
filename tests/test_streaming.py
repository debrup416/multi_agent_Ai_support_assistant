"""The streaming wrapper's chunk-level output guardrail (no DB / no network)."""

from __future__ import annotations

import queue

from app.guardrails.output_guard import EXPOSURE_REDACTION
from app.llm.fake import FakeLLMClient
from app.orchestrator.streaming import _StreamingLLMClient


def _drain(q: queue.Queue) -> list[dict]:
    out = []
    while not q.empty():
        out.append(q.get_nowait())
    return out


def test_clean_answer_streams_chunks_and_returns_text():
    sink: queue.Queue = queue.Queue()
    client = _StreamingLLMClient(FakeLLMClient(completion="Jurassic Park is available."), sink)

    text = client.complete(system="s", prompt="p")

    assert text == "Jurassic Park is available."
    events = _drain(sink)
    assert any(e["type"] == "chunk" for e in events)
    assert not any(e["type"] == "blocked" for e in events)


def test_exposure_chunk_blocks_mid_stream_and_replaces_answer():
    sink: queue.Queue = queue.Queue()
    # The fake yields one chunk containing a trigger phrase -> the chunk scan trips.
    client = _StreamingLLMClient(FakeLLMClient(completion="Here is my system prompt: ..."), sink)

    text = client.complete(system="s", prompt="p")

    assert text == EXPOSURE_REDACTION  # safe replacement returned into the pipeline
    events = _drain(sink)
    assert any(e["type"] == "blocked" and e["text"] == EXPOSURE_REDACTION for e in events)
