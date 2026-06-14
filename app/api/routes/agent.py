"""The core graded endpoint: POST /agent/respond."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.deps import get_llm
from app.llm import LLMClient
from app.orchestrator import respond
from app.orchestrator.streaming import stream_response
from app.schemas.contracts import AgentRequest, AgentResponse

router = APIRouter(tags=["agent"])


@router.post("/agent/respond", response_model=AgentResponse)
def agent_respond(
    request: AgentRequest, llm: LLMClient = Depends(get_llm)
) -> AgentResponse:
    """Run the full multi-agent pipeline and return the stable response contract."""
    return respond(request, llm)


@router.post("/agent/respond/stream")
def agent_respond_stream(
    request: AgentRequest, llm: LLMClient = Depends(get_llm)
) -> StreamingResponse:
    """Same pipeline, streamed: NDJSON ``chunk``/``blocked``/``done`` events. The answer is
    validated chunk-by-chunk and cut over to a safe reply if a guardrail trips mid-stream."""
    return StreamingResponse(
        stream_response(request, llm),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
