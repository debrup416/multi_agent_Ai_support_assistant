"""Introspection of the fixed agent registry and routing table."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.agents.registry import AGENTS, FALLBACK, ROUTES
from app.config import get_settings

router = APIRouter(tags=["agents"])


def _agent_view(agent) -> dict:
    return {
        "name": agent.name,
        "responsibility": agent.responsibility,
        "tools": agent.tool_names,
    }


@router.get("/agents")
def list_agents() -> list[dict]:
    """List the fixed specialist agents and their bound tools."""
    return [_agent_view(a) for a in AGENTS.values()]


@router.get("/agents/{name}")
def get_agent(name: str) -> dict:
    """One agent's responsibility and bound tools."""
    agent = AGENTS.get(name)
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Unknown agent: {name}")
    return _agent_view(agent)


@router.get("/routes")
def routing_table() -> dict:
    """The deterministic intent->agent table, threshold, and fallback agent."""
    return {
        "confidence_threshold": get_settings().confidence_threshold,
        "fallback_agent": FALLBACK.name,
        "routes": {intent: agent.name for intent, agent in ROUTES.items()},
    }
