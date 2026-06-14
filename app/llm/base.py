"""Provider-swappable LLM client interface.

Reasoning components depend only on this Protocol, never on a concrete SDK. Two
methods: ``complete`` (free-text answers) and ``complete_structured`` (schema-validated
objects with a bounded repair loop). A single LiteLLM-backed adapter
(:class:`~app.llm.litellm_client.LiteLLMClient`) implements this for every provider;
the provider/model are resolved from the environment (see :class:`~app.config.Settings`).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Base class for LLM failures surfaced to the orchestrator."""


class StructuredOutputError(LLMError):
    """Raised when structured output cannot be produced/validated after repair."""


class LLMClient(Protocol):
    """The contract every provider adapter implements."""

    def complete(self, *, system: str, prompt: str, max_tokens: int | None = None) -> str:
        """Return a free-text completion."""
        ...

    def stream_complete(
        self, *, system: str, prompt: str, max_tokens: int | None = None
    ) -> Iterator[str]:
        """Yield a free-text completion in chunks (for streaming responses)."""
        ...

    def complete_structured(
        self, *, system: str, prompt: str, schema: type[T], max_tokens: int | None = None
    ) -> T:
        """Return an instance of ``schema``, repaired/failed-closed on invalid output."""
        ...
