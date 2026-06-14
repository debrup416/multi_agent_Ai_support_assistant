"""A deterministic fake LLM client for tests and offline development.

Lets tests assert routing and guardrail behavior without network calls or
nondeterminism. Configure canned structured outputs per schema and a default
completion string.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from pydantic import BaseModel

from app.llm.base import LLMClient, StructuredOutputError, T


class FakeLLMClient(LLMClient):
    """Returns canned responses; records the prompts it received."""

    def __init__(
        self,
        *,
        completion: str | Callable[[str], str] = "OK",
        structured: dict[type, BaseModel] | None = None,
    ) -> None:
        self._completion = completion
        self._structured = structured or {}
        self.calls: list[tuple[str, str]] = []

    def complete(self, *, system: str, prompt: str, max_tokens: int | None = None) -> str:
        self.calls.append(("complete", prompt))
        if callable(self._completion):
            return self._completion(prompt)
        return self._completion

    def stream_complete(
        self, *, system: str, prompt: str, max_tokens: int | None = None
    ) -> Iterator[str]:
        self.calls.append(("stream", prompt))
        yield self._completion(prompt) if callable(self._completion) else self._completion

    def complete_structured(
        self, *, system: str, prompt: str, schema: type[T], max_tokens: int | None = None
    ) -> T:
        self.calls.append(("structured", prompt))
        if schema in self._structured:
            return self._structured[schema]  # type: ignore[return-value]
        raise StructuredOutputError(f"FakeLLMClient has no canned output for {schema.__name__}")
