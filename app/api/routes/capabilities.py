"""UI capability discovery.

The static frontend calls ``GET /capabilities`` once on load to (a) build the runtime
switcher — ``adk`` / ``sk`` mount conditionally, so the UI must learn what is actually
available — and (b) label the confidence bar / status pills without a second round-trip
to ``/config``. Kept separate from ``/config`` so the existing config contract is untouched.
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/capabilities")
def capabilities(request: Request) -> dict:
    """Which agent runtimes are mounted, plus a few non-secret display hints for the UI."""
    settings = get_settings()
    public = settings.public_view()
    return {
        "runtimes": list(getattr(request.app.state, "runtimes", ["core"])),
        "active_provider": public["active_provider"],
        "active_model": public["active_model"],
        "confidence_threshold": settings.confidence_threshold,
    }
