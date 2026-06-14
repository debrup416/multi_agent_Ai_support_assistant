"""Shared FastAPI dependencies."""

from __future__ import annotations

from app.llm import LLMClient, get_llm_client


def get_llm() -> LLMClient:
    """Return the configured LLM client. Overridable in tests via dependency_overrides."""
    return get_llm_client()
