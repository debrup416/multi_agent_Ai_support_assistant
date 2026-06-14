"""Generic LiteLLM adapter for :class:`~app.llm.base.LLMClient`.

One implementation for every provider (Anthropic, OpenAI, ...). Provider, model, key
and timeout are resolved from :class:`~app.config.Settings`; the API key is passed
explicitly to LiteLLM rather than relied upon via ``os.environ``.

Structured output uses ``response_format=<PydanticModel>``: LiteLLM returns the content
as a JSON *string* (there is no ``.parsed`` attribute — that is the OpenAI SDK), so we
validate it into the model ourselves with ``model_validate_json``. A bounded repair loop
re-prompts on invalid output, then fails closed with :class:`StructuredOutputError`.
"""

from __future__ import annotations

from collections.abc import Iterator

import litellm

from app.config import Settings
from app.llm.base import LLMClient, StructuredOutputError, T
from app.observability import tracing
from app.observability.logging import get_logger, log_event

_logger = get_logger("llm.litellm")

# Defense in depth: LiteLLM also validates the JSON against the schema and raises
# litellm.JSONSchemaValidationError. Our ``model_validate_json`` is authoritative.
litellm.enable_json_schema_validation = True


class LiteLLMClient(LLMClient):
    """Provider-agnostic LLM client backed by LiteLLM."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Resolve once at construction so misconfiguration fails fast.
        self._model = settings.litellm_model_string
        self._api_key = settings.active_api_key.get_secret_value()

    def _emit_usage(
        self, response: object, *, name: str, input_messages: list[dict], output: str
    ) -> None:
        """Emit token usage + cost to both the JSON logs and Langfuse (as a GENERATION).

        Extracts ``response.usage`` and LiteLLM's computed ``response_cost`` once, then (a)
        logs an ``llm_usage`` line (gated by ``langfuse_cost_tracking``, works even with
        Langfuse off) and (b) records a Langfuse generation with model/prompt/output/tokens/
        cost (no-op when observability is off). Defensive: faked responses lack these fields.
        """
        usage = getattr(response, "usage", None)
        hidden = getattr(response, "_hidden_params", None)
        cost = hidden.get("response_cost") if isinstance(hidden, dict) else None
        prompt_tokens = getattr(usage, "prompt_tokens", None) if usage is not None else None
        completion_tokens = getattr(usage, "completion_tokens", None) if usage is not None else None
        total_tokens = getattr(usage, "total_tokens", None) if usage is not None else None
        if self._settings.langfuse_cost_tracking and usage is not None:
            log_event(
                _logger,
                "llm_usage",
                model=self._model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_usd=cost,
            )
        tracing.record_generation(
            name=name,
            model=self._model,
            input=input_messages,
            output=output,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
        )

    def complete(self, *, system: str, prompt: str, max_tokens: int | None = None) -> str:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        response = litellm.completion(
            model=self._model,
            api_key=self._api_key,
            timeout=self._settings.llm_timeout_seconds,
            max_tokens=max_tokens or self._settings.llm_max_tokens,
            messages=messages,
        )
        text = response.choices[0].message.content or ""
        log_event(_logger, "llm_complete", model=self._model, output_chars=len(text))
        self._emit_usage(response, name="core.complete", input_messages=messages, output=text)
        return text.strip()

    def stream_complete(
        self, *, system: str, prompt: str, max_tokens: int | None = None
    ) -> Iterator[str]:
        response = litellm.completion(
            model=self._model,
            api_key=self._api_key,
            timeout=self._settings.llm_timeout_seconds,
            max_tokens=max_tokens or self._settings.llm_max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            stream=True,
        )
        for chunk in response:
            delta = chunk.choices[0].delta.content
            if delta:
                yield delta
        log_event(_logger, "llm_stream_complete", model=self._model)

    def complete_structured(
        self, *, system: str, prompt: str, schema: type[T], max_tokens: int | None = None
    ) -> T:
        messages: list[dict] = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        last_error: Exception | None = None
        # 1 initial attempt + N repair attempts.
        for attempt in range(self._settings.max_repair_attempts + 1):
            try:
                response = litellm.completion(
                    model=self._model,
                    api_key=self._api_key,
                    timeout=self._settings.llm_timeout_seconds,
                    max_tokens=max_tokens or self._settings.llm_max_tokens,
                    messages=messages,
                    response_format=schema,
                )
                content = response.choices[0].message.content
                if not content:
                    raise StructuredOutputError("model returned no structured output")
                parsed = schema.model_validate_json(content)
                log_event(
                    _logger,
                    "llm_structured",
                    model=self._model,
                    schema=schema.__name__,
                    attempt=attempt,
                )
                self._emit_usage(
                    response, name="core.structured", input_messages=messages, output=content
                )
                return parsed
            except Exception as exc:  # noqa: BLE001 — re-prompt with the error, then fail closed
                last_error = exc
                messages = [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous response was invalid ({exc}). Return ONLY data that "
                            f"matches the required schema, with no extra text."
                        ),
                    },
                ]
        log_event(
            _logger,
            "llm_structured_failed",
            model=self._model,
            schema=schema.__name__,
            error=str(last_error),
        )
        raise StructuredOutputError(
            f"structured output failed after {self._settings.max_repair_attempts} repairs: {last_error}"
        )
