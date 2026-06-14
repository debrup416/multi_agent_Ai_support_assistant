"""Streaming variant of the core pipeline.

Reuses ``respond()`` and all five specialists **unchanged**. The trick: every specialist
runs its tool(s) first and then makes a single ``llm.complete()`` call for the answer
text — so routing, tools and citations are settled before the first token. We pass the
specialist a ``_StreamingLLMClient`` that turns that one ``complete()`` into a token
stream, pushing each chunk to a queue and validating the accumulated text with the output
guardrail's exposure check. If a chunk trips it, streaming stops and a safe replacement is
emitted (and returned into the pipeline, which finishes normally and yields the
authoritative ``AgentResponse``).

The pipeline is synchronous, so it runs in a worker thread that feeds a queue; the
generator drains the queue and yields NDJSON lines (``chunk`` / ``blocked`` / ``done`` /
``error``).
"""

from __future__ import annotations

import json
import queue
import threading
from collections.abc import AsyncIterator, Iterator

import anyio

from app.guardrails.output_guard import EXPOSURE_REDACTION, scan_exposure
from app.llm.base import LLMClient, T
from app.orchestrator.orchestrator import respond
from app.schemas.contracts import AgentRequest

_END = object()  # sentinel: producer thread is done


class _StreamingLLMClient:
    """Wraps an ``LLMClient`` so the specialist's ``complete()`` streams, chunk-validated."""

    def __init__(self, inner: LLMClient, sink: queue.Queue) -> None:
        self._inner = inner
        self._sink = sink

    def complete(self, *, system: str, prompt: str, max_tokens: int | None = None) -> str:
        acc: list[str] = []
        for delta in self._inner.stream_complete(system=system, prompt=prompt, max_tokens=max_tokens):
            acc.append(delta)
            # ponytail: re-scan the accumulated text each chunk (catches matches that span a
            # chunk boundary). Answers are short, so the repeated scan is cheap.
            if scan_exposure("".join(acc)):
                self._sink.put({"type": "blocked", "text": EXPOSURE_REDACTION})
                return EXPOSURE_REDACTION  # safe text flows through the rest of the pipeline
            self._sink.put({"type": "chunk", "text": delta})
        return "".join(acc).strip()

    # Triage etc. are not streamed — pass structured calls straight through.
    def complete_structured(
        self, *, system: str, prompt: str, schema: type[T], max_tokens: int | None = None
    ) -> T:
        return self._inner.complete_structured(
            system=system, prompt=prompt, schema=schema, max_tokens=max_tokens
        )

    def stream_complete(
        self, *, system: str, prompt: str, max_tokens: int | None = None
    ) -> Iterator[str]:
        return self._inner.stream_complete(system=system, prompt=prompt, max_tokens=max_tokens)


async def stream_response(request: AgentRequest, llm: LLMClient) -> AsyncIterator[str]:
    """Run the (sync) pipeline in a thread; yield NDJSON events as the answer streams.

    An async generator so Starlette/uvicorn flush each line to the client immediately
    (a blocking sync generator can be buffered by the threadpool iterator).
    """
    sink: queue.Queue = queue.Queue()

    def run() -> None:
        try:
            response = respond(request, _StreamingLLMClient(llm, sink))
            sink.put({"type": "done", "response": response.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001 -- surface to the client, then end the stream
            sink.put({"type": "error", "detail": str(exc)})
        finally:
            sink.put(_END)

    threading.Thread(target=run, daemon=True).start()

    while True:
        event = await anyio.to_thread.run_sync(sink.get)  # offload the blocking get
        if event is _END:
            break
        yield json.dumps(event) + "\n"
