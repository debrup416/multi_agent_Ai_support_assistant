"""Typed application settings.

All configuration comes from the environment (``.env`` locally). Secrets are held
as ``SecretStr`` so they are never accidentally serialized — the ``/config`` endpoint
reflects only the non-secret view returned by :meth:`Settings.public_view`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration, loaded once from the environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- Database -------------------------------------------------------------
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/pagila",
        description="SQLAlchemy URL for the Pagila Postgres database.",
    )
    db_statement_timeout_ms: int = 5000
    db_pool_size: int = 5
    db_max_overflow: int = 5

    # --- LLM provider ---------------------------------------------------------
    # Provider is auto-detected from which API key is present, unless explicitly
    # overridden here. Anthropic wins when both keys are set. See `active_provider`.
    llm_provider: Literal["anthropic", "openai"] | None = None
    # Per-provider models, both configurable via .env (ANTHROPIC_MODEL / OPENAI_MODEL).
    # The design leans on deterministic routing, so a small/fast tier is sufficient.
    anthropic_model: str = "claude-haiku-4-5"
    openai_model: str = "gpt-5.4-mini"
    anthropic_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    llm_max_tokens: int = 1024
    llm_timeout_seconds: float = 30.0
    max_repair_attempts: int = 2

    # --- Routing / behavior ---------------------------------------------------
    confidence_threshold: float = 0.55
    catalog_result_limit: int = 10
    rental_history_limit: int = 10
    kb_result_limit: int = 3

    # --- Google ADK agent layer (optional `adk` extra) ------------------------
    # The ADK agents reach the same tools over the pagila-support-mcp server.
    # Streamable HTTP by default (connect to a running server); "stdio" lets ADK
    # spawn `python -m app.mcp.server` itself. The model is resolved the same way
    # as the core path, via `litellm_model_string`.
    adk_mcp_transport: Literal["http", "stdio"] = "http"
    adk_mcp_url: str = "http://127.0.0.1:8765/mcp"

    # --- ADK guardrails (optional `guardrails` extra: Guardrails AI) -----------
    # Wraps Guardrails AI Guards/Validators in an ADK plugin on the ADK runner.
    # The shipped validators are regex (offline, no Hub token). Set
    # adk_guardrails_ml_injection=true to additionally use the Hub's ML
    # DetectJailbreak validator (requires `guardrails hub install`).
    adk_guardrails_enabled: bool = True
    adk_guardrails_ml_injection: bool = False

    # --- Semantic Kernel agent layer (optional `sk` extra) --------------------
    # A third runtime (Microsoft Semantic Kernel) over the same MCP tools. Like the ADK
    # layer it picks the MCP transport once: streamable HTTP by default (connect to a
    # running server), or stdio (SK spawns `python -m app.mcp.server`). The model is
    # resolved the same way as the core path, via `litellm_model_string`. The `sk` and `adk`
    # extras can be installed together (sk>=1.43 + google-adk coexist on pydantic 2.12/2.13).
    sk_mcp_transport: Literal["http", "stdio"] = "http"
    sk_mcp_url: str = "http://127.0.0.1:8765/mcp"

    # --- Semantic Kernel guardrails (optional `guardrails` extra: Guardrails AI) ---
    # Same posture as the ADK guardrails, wired the SK-idiomatic way: input
    # injection->block / mutation->escalate as a pre-step in the runner, output
    # system-prompt-leak redaction as an SK function-invocation filter.
    sk_guardrails_enabled: bool = True

    # --- Observability --------------------------------------------------------
    log_level: str = "INFO"

    # --- Langfuse tracing (optional `observability` extra) --------------------
    # Off by default: with the extra uninstalled, keys absent, or this flag false,
    # the whole tracing seam (app/observability/tracing.py) is a no-op and behavior
    # is byte-for-byte unchanged. When active, LiteLLM's native "langfuse" callback
    # captures model/prompt/usage/cost for all three runtimes and our manual spans add
    # the request/tool structure, correlated by conversation_id -> Langfuse session_id.
    langfuse_enabled: bool = False
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None
    langfuse_host: str = "http://localhost:3000"
    # Privacy switch: when false, send usage/cost/metadata but NOT raw prompt/tool text.
    langfuse_capture_io: bool = True
    # Gates the manual usage/cost log fallback (independent of Langfuse being up).
    langfuse_cost_tracking: bool = True

    @property
    def observability_active(self) -> bool:
        """Single predicate the tracing seam checks: enabled AND both keys present.

        Keys absent ⇒ inactive ⇒ every tracing function is a no-op. (Import
        availability of the optional ``langfuse`` package is checked separately in
        ``app.observability.tracing``.)
        """
        return (
            self.langfuse_enabled
            and self.langfuse_public_key is not None
            and self.langfuse_secret_key is not None
        )

    @property
    def active_provider(self) -> Literal["anthropic", "openai"]:
        """Resolve the provider: explicit override wins, else auto-detect by key.

        Anthropic is preferred when both keys are present. Raises if neither key
        is set and no override is given.
        """
        if self.llm_provider is not None:
            return self.llm_provider
        if self.anthropic_api_key is not None:
            return "anthropic"
        if self.openai_api_key is not None:
            return "openai"
        raise ValueError(
            "No LLM provider configured: set ANTHROPIC_API_KEY or OPENAI_API_KEY "
            "(or set LLM_PROVIDER explicitly)."
        )

    @property
    def active_model(self) -> str:
        """The model id for the resolved provider."""
        return self.anthropic_model if self.active_provider == "anthropic" else self.openai_model

    @property
    def active_api_key(self) -> SecretStr:
        """API key for the resolved provider; raises if it is missing.

        An explicit ``LLM_PROVIDER`` override can name a provider whose key is absent.
        """
        provider = self.active_provider
        key = self.anthropic_api_key if provider == "anthropic" else self.openai_api_key
        if key is None:
            raise ValueError(f"LLM provider '{provider}' is selected but its API key is not set.")
        return key

    @property
    def litellm_model_string(self) -> str:
        """LiteLLM model identifier, e.g. ``anthropic/claude-haiku-4-5`` or ``openai/gpt-5.4-mini``."""
        return f"{self.active_provider}/{self.active_model}"

    def public_view(self) -> dict[str, object]:
        """Non-secret config for the ``/config`` endpoint. Never includes keys."""
        try:
            active_provider: str | None = self.active_provider
            active_model: str | None = self.active_model
            litellm_model_string: str | None = self.litellm_model_string
        except ValueError:
            # No key and no override — surface nulls rather than crashing /config.
            active_provider = active_model = litellm_model_string = None
        return {
            "active_provider": active_provider,
            "active_model": active_model,
            "litellm_model_string": litellm_model_string,
            "llm_provider_override": self.llm_provider,
            "anthropic_model": self.anthropic_model,
            "openai_model": self.openai_model,
            "llm_max_tokens": self.llm_max_tokens,
            "llm_timeout_seconds": self.llm_timeout_seconds,
            "max_repair_attempts": self.max_repair_attempts,
            "confidence_threshold": self.confidence_threshold,
            "catalog_result_limit": self.catalog_result_limit,
            "rental_history_limit": self.rental_history_limit,
            "kb_result_limit": self.kb_result_limit,
            "db_statement_timeout_ms": self.db_statement_timeout_ms,
            "log_level": self.log_level,
            "adk_mcp_transport": self.adk_mcp_transport,
            "adk_mcp_url": self.adk_mcp_url,
            "adk_guardrails_enabled": self.adk_guardrails_enabled,
            "adk_guardrails_ml_injection": self.adk_guardrails_ml_injection,
            "sk_mcp_transport": self.sk_mcp_transport,
            "sk_mcp_url": self.sk_mcp_url,
            "sk_guardrails_enabled": self.sk_guardrails_enabled,
            "langfuse_enabled": self.langfuse_enabled,
            "langfuse_host": self.langfuse_host,
            "langfuse_capture_io": self.langfuse_capture_io,
            "langfuse_cost_tracking": self.langfuse_cost_tracking,
            "observability_active": self.observability_active,
            "anthropic_key_present": self.anthropic_api_key is not None,
            "openai_key_present": self.openai_api_key is not None,
            "langfuse_public_key_present": self.langfuse_public_key is not None,
            "langfuse_secret_key_present": self.langfuse_secret_key is not None,
        }


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings singleton."""
    return Settings()
