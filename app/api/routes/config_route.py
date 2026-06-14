"""Expose non-secret runtime configuration."""

from __future__ import annotations

from fastapi import APIRouter

from app.config import get_settings

router = APIRouter(tags=["system"])


@router.get("/config")
def get_config() -> dict:
    """Non-secret runtime config. Never returns API keys."""
    return get_settings().public_view()
