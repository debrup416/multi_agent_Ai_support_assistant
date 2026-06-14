"""Run only the triage classifier — for debugging routing decisions."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.agents import triage
from app.api.deps import get_llm
from app.llm import LLMClient
from app.schemas.contracts import AgentContext, AgentRequest, TriageDecision

router = APIRouter(tags=["debug"])


class TriageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: str = "triage-debug"


@router.post("/triage", response_model=TriageDecision)
def run_triage(req: TriageRequest, llm: LLMClient = Depends(get_llm)) -> TriageDecision:
    """Classify a message without running a specialist."""
    ctx = AgentContext(
        request=AgentRequest(conversation_id=req.conversation_id, message=req.message),
        intent="",
        confidence=0.0,
    )
    return triage(ctx, llm)
