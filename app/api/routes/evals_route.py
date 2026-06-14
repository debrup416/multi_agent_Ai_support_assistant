"""List and run the eval suite from the API (the human-driven end-to-end check)."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_llm
from app.llm import LLMClient
from evals import CASES, run_evals

router = APIRouter(tags=["evals"])


@router.get("/evals")
def list_evals() -> list[dict]:
    """List the eval cases (input + expectations)."""
    return [
        {
            "name": c.name,
            "message": c.message,
            "customer_id": c.customer_id,
            "expected_intent": c.expected_intent,
            "expected_agent": c.expected_agent,
            "expected_tools": c.expected_tools,
            "safety_behavior": c.safety_behavior,
        }
        for c in CASES
    ]


@router.post("/evals/run")
def evals_run(llm: LLMClient = Depends(get_llm)) -> dict:
    """Run every eval case through the real pipeline; return pass/fail + summary."""
    return run_evals(llm)
