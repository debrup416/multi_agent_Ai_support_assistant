"""Guardrails for the Semantic Kernel layer — a standard framework (Guardrails AI).

The SK-side counterpart to the core ``app/guardrails/`` and the ADK ``GuardrailPlugin``.
Same safety posture, wired the way SK affords it:

- **Input** (injection -> block, sensitive mutation -> escalate): SK has no inbound-message
  hook, so the runner calls :meth:`SkGuardrails.screen_input` as a pre-step and short-circuits.
- **Output** (system-prompt / internal-detail leak -> redact): an SK function-invocation
  filter only sees *tool* calls, never the model's final text, so redaction is a runner
  post-step via :meth:`SkGuardrails.redact_output`.

Detection reuses the same regexes and canned wording as the other layers, wrapped in
Guardrails AI ``Guard``/``Validator`` objects. The whole thing is optional: if the
``guardrails`` extra isn't installed or ``sk_guardrails_enabled`` is false, ``build_guardrails``
returns ``None`` and the runtime runs unguarded (logged), exactly like the ADK layer.
"""

from __future__ import annotations

import logging
import re

from app.config import Settings, get_settings

_logger = logging.getLogger("sk.guardrails")

# Canned replies (kept consistent with the core/ADK guardrails' wording/posture).
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
# the optional SK layer never imports core guardrail internals (and never the ADK extra).
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
_EXPOSURE = re.compile(r"system\s+prompt|you are the .{0,40}specialist|TRIAGE", re.I)


def _matches(patterns: list[re.Pattern[str]], value: str | None) -> bool:
    return bool(value) and any(p.search(value) for p in patterns)


try:
    from guardrails import Guard, OnFailAction
    from guardrails.classes.validation.validation_result import (
        FailResult,
        PassResult,
        ValidationResult,
    )
    from guardrails.validator_base import Validator, register_validator

    def _fail_if(patterns: list[re.Pattern[str]], value: str | None, reason: str) -> "ValidationResult":
        return FailResult(error_message=reason) if _matches(patterns, value) else PassResult()

    @register_validator(name="pagila_sk/prompt_injection", data_type="string")
    class _PromptInjectionValidator(Validator):
        """Fail on prompt-injection / system-prompt exfiltration attempts."""

        def validate(self, value, metadata):  # noqa: ARG002 -- Validator API
            return _fail_if(_INJECTION, value, "prompt_injection_or_exfiltration")

    @register_validator(name="pagila_sk/sensitive_mutation", data_type="string")
    class _SensitiveMutationValidator(Validator):
        """Fail on sensitive account mutations (cancel / refund / close)."""

        def validate(self, value, metadata):  # noqa: ARG002 -- Validator API
            return _fail_if(_MUTATION, value, "sensitive_account_mutation")

    @register_validator(name="pagila_sk/system_prompt_leak", data_type="string")
    class _SystemPromptLeakValidator(Validator):
        """Fail when an answer leaks the system prompt or internal identifiers."""

        def validate(self, value, metadata):  # noqa: ARG002 -- Validator API
            return _fail_if([_EXPOSURE], value, "system_prompt_or_internal_exposure")

    _GUARDRAILS_AVAILABLE = True
except ImportError:  # pragma: no cover -- the `guardrails` extra is optional
    _GUARDRAILS_AVAILABLE = False


class SkGuardrails:
    """Guardrails AI ``Guard``s for the SK runtime: input screen + output redaction."""

    def __init__(self) -> None:
        self._injection_guard = Guard().use(_PromptInjectionValidator(on_fail=OnFailAction.NOOP))
        self._mutation_guard = Guard().use(_SensitiveMutationValidator(on_fail=OnFailAction.NOOP))
        self._leak_guard = Guard().use(_SystemPromptLeakValidator(on_fail=OnFailAction.NOOP))

    def screen_input(self, message: str) -> str | None:
        """Return a canned reply to short-circuit a blocked/escalated message, else None."""
        if not self._injection_guard.validate(message).validation_passed:
            _logger.info("guardrail_block", extra={"event": {"reason": "prompt_injection"}})
            return SAFE_INJECTION_ANSWER
        if not self._mutation_guard.validate(message).validation_passed:
            _logger.info("guardrail_escalate", extra={"event": {"reason": "sensitive_mutation"}})
            # Mirror the core path: a sensitive mutation creates a (mock) handoff ticket so it
            # shows up for an operator — we just never execute the mutation itself.
            from app.service import create_handoff_ticket

            create_handoff_ticket(message[:500], "sensitive_account_mutation", source="sk")
            return ESCALATION_ANSWER
        return None

    def redact_output(self, answer: str) -> str:
        """Replace an answer that leaks the system prompt / internals with a safe reply."""
        if answer and not self._leak_guard.validate(answer).validation_passed:
            _logger.info("guardrail_redact", extra={"event": {"reason": "system_prompt_leak"}})
            return REDACTION_ANSWER
        return answer


def build_guardrails(settings: Settings | None = None) -> SkGuardrails | None:
    """Construct the guardrails, or None when disabled / the extra isn't installed."""
    s = settings or get_settings()
    if not s.sk_guardrails_enabled:
        return None
    if not _GUARDRAILS_AVAILABLE:
        _logger.info(
            "SK guardrails disabled (guardrails-ai not installed; `uv sync --extra guardrails`)."
        )
        return None
    return SkGuardrails()
