"""Provider-swappable LLM client."""

from functools import lru_cache

from app.config import get_settings
from app.llm.base import LLMClient, LLMError, StructuredOutputError
from app.llm.fake import FakeLLMClient

__all__ = [
    "LLMClient",
    "LLMError",
    "StructuredOutputError",
    "FakeLLMClient",
    "get_llm_client",
]


@lru_cache
def get_llm_client() -> LLMClient:
    """Return the configured LLM client.

    A single LiteLLM-backed adapter serves every provider; the provider and model are
    auto-detected from the API keys in the environment (Anthropic preferred when both
    are present) unless ``LLM_PROVIDER`` overrides it. See :class:`~app.config.Settings`.
    """
    from app.llm.litellm_client import LiteLLMClient

    return LiteLLMClient(get_settings())
