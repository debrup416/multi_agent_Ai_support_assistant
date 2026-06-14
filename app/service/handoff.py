"""Mock human-handoff sink.

``create_handoff_ticket`` is the only "write" in the system, and it writes to a file
sink (plus a structured log line) — never to customer account state. The ``/handoffs``
routes read this same sink so an operator can see escalations.

A *file* rather than an in-process dict because the ADK/SK agents create tickets inside
the separate ``app.mcp.server`` process; a shared file is the one sink every process
(API + MCP server) can see, so operator views show every runtime's tickets.
"""

from __future__ import annotations

import os
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.observability.logging import get_logger, log_event
from app.schemas.tools import HandoffResult

_logger = get_logger("service.handoff")

# Shared, append-only sink. Same path across processes on one machine; resets only when the
# temp file is removed — sufficient for the assignment's mock scope.
# ponytail: JSONL append, no locking/rotation. Handoffs are rare and one-at-a-time here;
# swap for a DB/queue if this ever sees real concurrency or needs durability.
_SINK = Path(
    os.environ.get(
        "HANDOFF_SINK_PATH", str(Path(tempfile.gettempdir()) / "pagila_support_handoffs.jsonl")
    )
)


def create_handoff_ticket(
    summary: str,
    reason: str,
    *,
    customer_id: int | None = None,
    conversation_id: str | None = None,
    source: str = "core",
) -> HandoffResult:
    """Simulate creating a human-support escalation ticket."""
    ticket = HandoffResult(
        ticket_id=f"HND-{uuid.uuid4().hex[:8]}",
        status="created",
        created_at=datetime.now(timezone.utc),
        summary=summary,
        reason=reason,
        source=source,
    )
    with _SINK.open("a", encoding="utf-8") as fh:
        fh.write(ticket.model_dump_json() + "\n")
    log_event(
        _logger,
        "handoff_ticket_created",
        ticket_id=ticket.ticket_id,
        reason=reason,
        customer_id=customer_id,
        source=source,
    )
    return ticket


def _read_all() -> list[HandoffResult]:
    if not _SINK.exists():
        return []
    tickets: list[HandoffResult] = []
    with _SINK.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                tickets.append(HandoffResult.model_validate_json(line))
    return tickets


def list_handoff_tickets() -> list[HandoffResult]:
    """All tickets in the sink, newest first."""
    return sorted(_read_all(), key=lambda t: t.created_at, reverse=True)


def get_handoff_ticket(ticket_id: str) -> HandoffResult | None:
    """One ticket by id, or None."""
    return next((t for t in _read_all() if t.ticket_id == ticket_id), None)
