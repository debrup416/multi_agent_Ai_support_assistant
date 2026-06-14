"""Guardrails for the ADK agents — a standard framework (Guardrails AI) wrapped in one
ADK plugin.

This is the ADK-side counterpart to the core system's `app/guardrails/`. Instead of the
core's hand-rolled checks it uses **Guardrails AI** `Guard`/`Validator` objects, and instead
of being a pipeline stage it is a single `BasePlugin` registered on the ADK `Runner` — so it
covers the coordinator *and* all five specialists at once. Verified hooks (google-adk 2.2.0):

- `on_user_message_callback` fires once per user turn; returning a `Content` short-circuits
  the whole run — used to **block** prompt-injection and **escalate** sensitive mutations.
- `after_model_callback` fires per model call; returning an `LlmResponse` replaces the
  answer — used to **redact** a system-prompt/internal leak.

The shipped validators are regex (offline, no Hub token) and mirror the intent of
`app/guardrails/input_guard.py` / `output_guard.py`. Set `adk_guardrails_ml_injection=true`
to additionally pull in the Hub's ML `DetectJailbreak` validator (needs `guardrails hub
install hub://guardrails/detect_jailbreak`); it is skipped gracefully if not installed.
"""

from __future__ import annotations

import logging
import re

from google.adk.models.llm_response import LlmResponse
from google.adk.plugins.base_plugin import BasePlugin
from google.genai import types
from guardrails import Guard, OnFailAction
from guardrails.classes.validation.validation_result import (
    FailResult,
    PassResult,
    ValidationResult,
)
from guardrails.validator_base import Validator, register_validator

from app.config import Settings, get_settings

_logger = logging.getLogger("adk.guardrails")

# Canned replies (kept consistent with the core guardrails' wording/posture).
SAFE_INJECTION_ANSWER = (
    "I'm not able to share my internal instructions. I can help with films and "
    "streaming availability, your subscription, your rentals, or general support — "
    "what would you like to do?"
)
ESCALATION_ANSWER = (
    "It looks like you're asking to cancel, refund, or close your account. I've flagged "
    "this for a human support agent, who will follow up with you. Is there anything else "
    "I can help with in the meantime?"
)
REDACTION_ANSWER = (
    "I'm not able to share internal details, but I'm happy to help with your request — "
    "could you rephrase what you need?"
)

# Patterns mirror app/guardrails/input_guard.py and output_guard.py. Kept self-contained so
# the optional ADK layer never imports core guardrail internals.
_INJECTION = [
    re.compile(r"ignore\s+(all\s+)?(your\s+)?(previous|prior|above|earlier)\s+instructions", re.I),
    re.compile(r"disregard\s+(the\s+)?(previous|above|prior)", re.I),
    re.compile(r"(reveal|show|print|repeat|tell me)\s+(your\s+)?(the\s+)?system\s+prompt", re.I),
    re.compile(r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions)", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"developer\s+mode", re.I),
    re.compile(r"you\s+are\s+now\b", re.I),
]
# Narrow on purpose: "how do I cancel?" / "update my payment method" must NOT trip this.
_MUTATION = [
    re.compile(r"\bcancel\b.*\b(subscription|account|membership|plan)\b", re.I),
    re.compile(r"\b(close|delete|terminate)\b.*\b(account|subscription|membership)\b", re.I),
    re.compile(r"\brefund\b", re.I),
    re.compile(r"\bcharge\s*back\b", re.I),
]
_EXPOSURE = re.compile(r"system\s+prompt|you are the .{0,40}specialist|TRIAGE_SYSTEM", re.I)


def _fail_if_any(patterns: list[re.Pattern[str]], value: str | None, reason: str) -> ValidationResult:
    if value and any(p.search(value) for p in patterns):
        return FailResult(error_message=reason)
    return PassResult()


@register_validator(name="pagila/prompt_injection", data_type="string")
class PromptInjectionValidator(Validator):
    """Fail on prompt-injection / system-prompt exfiltration attempts."""

    def validate(self, value, metadata):  # noqa: ARG002 -- Validator API
        return _fail_if_any(_INJECTION, value, "prompt_injection_or_exfiltration")


@register_validator(name="pagila/sensitive_mutation", data_type="string")
class SensitiveMutationValidator(Validator):
    """Fail on sensitive account mutations (cancel / refund / close)."""

    def validate(self, value, metadata):  # noqa: ARG002 -- Validator API
        return _fail_if_any(_MUTATION, value, "sensitive_account_mutation")


@register_validator(name="pagila/system_prompt_leak", data_type="string")
class SystemPromptLeakValidator(Validator):
    """Fail when an answer leaks the system prompt or internal identifiers."""

    def validate(self, value, metadata):  # noqa: ARG002 -- Validator API
        return _fail_if_any([_EXPOSURE], value, "system_prompt_or_internal_exposure")


def _hub_jailbreak_validator() -> Validator | None:
    """The Hub's ML jailbreak detector, or None if it isn't installed."""
    try:
        from guardrails.hub import DetectJailbreak  # type: ignore
    except Exception:  # noqa: BLE001 -- optional, install via `guardrails hub install`
        _logger.info("DetectJailbreak not installed; skipping ML injection validator.")
        return None
    return DetectJailbreak(on_fail=OnFailAction.NOOP)


def _text_of(content: types.Content | None) -> str:
    if content is None:
        return ""
    return "".join(p.text or "" for p in (content.parts or []) if hasattr(p, "text"))


def _as_content(text: str) -> types.Content:
    return types.Content(role="model", parts=[types.Part(text=text)])


class GuardrailPlugin(BasePlugin):
    """One ADK plugin that guards every agent/model call via Guardrails AI."""

    def __init__(self, *, use_ml_injection: bool = False) -> None:
        super().__init__(name="guardrails_ai")
        injection: list[Validator] = [PromptInjectionValidator(on_fail=OnFailAction.NOOP)]
        if use_ml_injection and (ml := _hub_jailbreak_validator()) is not None:
            injection.append(ml)
        self._injection_guard = Guard().use(*injection)
        self._mutation_guard = Guard().use(SensitiveMutationValidator(on_fail=OnFailAction.NOOP))
        self._output_guard = Guard().use(SystemPromptLeakValidator(on_fail=OnFailAction.NOOP))

    async def before_agent_callback(self, *, agent, callback_context):  # noqa: ARG002
        """Screen the user message before an agent runs; return Content to short-circuit.

        This is the hook that actually halts execution in `Runner.run_async` — returning a
        `Content` bypasses the agent and uses it as the response. It fires for the
        coordinator first, so a blocked message never reaches a specialist.
        (`before_run_callback`/`on_user_message_callback` do not early-exit this runner.)
        """
        text = _text_of(getattr(callback_context, "user_content", None))
        if not text:
            return None
        if not self._injection_guard.validate(text).validation_passed:
            _logger.info("guardrail_block", extra={"reason": "prompt_injection"})
            return _as_content(SAFE_INJECTION_ANSWER)
        if not self._mutation_guard.validate(text).validation_passed:
            _logger.info("guardrail_escalate", extra={"reason": "sensitive_mutation"})
            # Mirror the core path: create a (mock) handoff ticket so an operator sees it; the
            # mutation itself is never executed.
            from app.service import create_handoff_ticket

            create_handoff_ticket(text[:500], "sensitive_account_mutation", source="adk")
            return _as_content(ESCALATION_ANSWER)
        return None

    async def after_model_callback(self, *, callback_context, llm_response):  # noqa: ARG002
        """Screen the model's answer; return a redacted LlmResponse on a leak."""
        text = _text_of(getattr(llm_response, "content", None))
        if text and not self._output_guard.validate(text).validation_passed:
            _logger.info("guardrail_redact", extra={"reason": "system_prompt_leak"})
            return llm_response.model_copy(update={"content": _as_content(REDACTION_ANSWER)})
        return None


def build_guardrail_plugin(settings: Settings | None = None) -> GuardrailPlugin | None:
    """Construct the plugin, or None when guardrails are disabled in settings."""
    s = settings or get_settings()
    if not s.adk_guardrails_enabled:
        return None
    return GuardrailPlugin(use_ml_injection=s.adk_guardrails_ml_injection)
