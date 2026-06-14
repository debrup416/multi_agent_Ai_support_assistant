"""Read the mock handoff sink (escalations created during the session)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.tools import HandoffResult
from app.service import get_handoff_ticket, list_handoff_tickets

router = APIRouter(tags=["handoffs"])


@router.get("/handoffs", response_model=list[HandoffResult])
def handoffs_list() -> list[HandoffResult]:
    """List handoff tickets in the mock sink, newest first."""
    return list_handoff_tickets()


@router.get("/handoffs/{ticket_id}", response_model=HandoffResult)
def handoffs_get(ticket_id: str) -> HandoffResult:
    """Fetch one handoff ticket by id."""
    ticket = get_handoff_ticket(ticket_id)
    if ticket is None:
        raise HTTPException(status_code=404, detail=f"Unknown ticket: {ticket_id}")
    return ticket
