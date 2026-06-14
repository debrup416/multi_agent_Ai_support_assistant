"""Input guardrails — run before triage/routing.

Deterministic, rule-based screening for the two things we must never leave to the
LLM: prompt-injection / system-prompt exfiltration (answered with a safe canned
response) and sensitive account mutations (cancel / refund / close — escalated to a
human, never executed). Missing-``customer_id`` handling is intent-dependent and
happens after triage, in the customer-scoped agents.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel

# Prompt-injection / system-prompt exfiltration.
_INJECTION_PATTERNS = [
    re.compile(r"ignore\s+(all\s+)?(your\s+)?(previous|prior|above|earlier)\s+instructions", re.I),
    re.compile(r"disregard\s+(the\s+)?(previous|above|prior)", re.I),
    re.compile(r"(reveal|show|print|repeat|tell me)\s+(your\s+)?(the\s+)?system\s+prompt", re.I),
    re.compile(r"what\s+(is|are)\s+your\s+(system\s+)?(prompt|instructions)", re.I),
    re.compile(r"system\s+prompt", re.I),
    re.compile(r"developer\s+mode", re.I),
    re.compile(r"you\s+are\s+now\b", re.I),
]

# Sensitive account mutations — escalate, never execute. Deliberately narrow so that
# how-to questions ("how do I update my payment method?") are NOT caught here.
_MUTATION_PATTERNS = [
    re.compile(r"\bcancel\b.*\b(subscription|account|membership|plan)\b", re.I),
    re.compile(r"\b(close|delete|terminate)\b.*\b(account|subscription|membership)\b", re.I),
    re.compile(r"\brefund\b", re.I),
    re.compile(r"\bcharge\s*back\b", re.I),
]

SAFE_INJECTION_ANSWER = (
    "I'm not able to share my internal instructions. I can help with films and "
    "streaming availability, your subscription, your rentals, or general support — "
    "what would you like to do?"
)


class InputVerdict(BaseModel):
    action: Literal["allow", "block", "handoff"]
    checks: list[str]
    reasons: list[str] = []
    canned_answer: str | None = None
    handoff_reason: str | None = None


def screen_input(message: str) -> InputVerdict:
    """Screen a raw message before any routing or tool use."""
    checks = ["prompt_injection", "sensitive_mutation"]

    for pattern in _INJECTION_PATTERNS:
        if pattern.search(message):
            return InputVerdict(
                action="block",
                checks=checks,
                reasons=["prompt_injection_or_system_prompt_exfiltration"],
                canned_answer=SAFE_INJECTION_ANSWER,
            )

    for pattern in _MUTATION_PATTERNS:
        if pattern.search(message):
            return InputVerdict(
                action="handoff",
                checks=checks,
                reasons=["sensitive_account_mutation"],
                handoff_reason="sensitive_account_mutation",
            )

    return InputVerdict(action="allow", checks=checks)
