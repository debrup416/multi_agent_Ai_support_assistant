"""JSON structured logging correlated by ``conversation_id``.

Every log line is a single JSON object so the whole pipeline (routing decision,
tool calls, guardrail result) is traceable from logs alone. The active
``conversation_id`` is carried in a :class:`~contextvars.ContextVar` so callers do
not have to thread it through every function.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, TextIO

_conversation_id: ContextVar[str | None] = ContextVar("conversation_id", default=None)


def set_conversation_id(conversation_id: str | None) -> None:
    """Bind the conversation id for all subsequent log lines on this task."""
    _conversation_id.set(conversation_id)


def get_conversation_id() -> str | None:
    """Return the conversation id bound on this task, if any.

    Used by the tracing seam to derive the Langfuse ``session_id`` without threading
    it through every call site.
    """
    return _conversation_id.get()


class JsonFormatter(logging.Formatter):
    """Render log records as one-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        conv = _conversation_id.get()
        if conv is not None:
            payload["conversation_id"] = conv
        # Structured fields attached via `extra={"event": {...}}`.
        event = getattr(record, "event", None)
        if isinstance(event, dict):
            payload.update(event)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", *, stream: TextIO = sys.stdout) -> None:
    """Install the JSON formatter on the root handler (idempotent).

    ``stream`` defaults to stdout; the MCP stdio transport passes stderr so logs
    never collide with the JSON-RPC protocol it writes to stdout.
    """
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())
    # Quiet noisy third-party loggers; we emit our own structured events.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Return a module logger."""
    return logging.getLogger(name)


def log_event(logger: logging.Logger, message: str, /, **fields: Any) -> None:
    """Emit a structured event: a human message plus arbitrary JSON fields."""
    logger.info(message, extra={"event": fields})
