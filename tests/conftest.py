"""Shared test fixtures: a fake LLM and a TestClient with the LLM overridden."""

from __future__ import annotations

import os

# Keep the suite hermetic: a developer's `.env` may enable Langfuse (LANGFUSE_ENABLED=true
# + keys), which would activate the tracing seam during tests and export spans to a real
# Langfuse backend. Force it off before any settings are loaded. (An explicit shell
# `LANGFUSE_ENABLED` still wins, for anyone who deliberately wants live tracing in tests.)
os.environ.setdefault("LANGFUSE_ENABLED", "false")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import create_app  # noqa: E402
from app.api.deps import get_llm  # noqa: E402
from app.llm.fake import FakeLLMClient  # noqa: E402
from app.schemas.contracts import TriageDecision  # noqa: E402


def make_fake(
    *, intent: str = "catalog_search", agent: str = "CatalogAgent", confidence: float = 0.95,
    completion: str = "Here is your answer.",
) -> FakeLLMClient:
    """A fake LLM that returns a fixed triage decision and completion."""
    return FakeLLMClient(
        completion=completion,
        structured={
            TriageDecision: TriageDecision(
                intent=intent, selected_agent=agent, confidence=confidence, reason="test"
            )
        },
    )


@pytest.fixture
def client_factory():
    """Build a TestClient whose LLM dependency is the given fake."""

    def _factory(fake: FakeLLMClient) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_llm] = lambda: fake
        return TestClient(app)

    return _factory
