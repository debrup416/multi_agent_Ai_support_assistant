"""Liveness and readiness probes."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.repository import connection

router = APIRouter(tags=["system"])


@router.get("/health")
def health() -> dict:
    """Liveness — the process is up."""
    return {"status": "ok"}


@router.get("/ready")
def ready() -> dict:
    """Readiness — database reachable and an LLM key is configured."""
    db_ok = True
    try:
        with connection() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:  # noqa: BLE001 — readiness reports the failure, doesn't raise
        db_ok = False
    settings = get_settings()
    llm_ok = settings.anthropic_api_key is not None or settings.openai_api_key is not None
    return {
        "status": "ok" if db_ok and llm_ok else "degraded",
        "database": db_ok,
        "llm_configured": llm_ok,
    }
