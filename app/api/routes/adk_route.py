"""Optional endpoint: POST /adk/respond — the Google ADK agent layer over HTTP.

A parallel to ``POST /agent/respond``: same request shape, but the answer is produced by
the ADK coordinator (``adk_agents``) driving Claude over MCP, not by the deterministic
pipeline. Importing this module pulls in ``google-adk``; ``app/api/main.py`` includes it
inside a ``try/except ImportError`` so the core API has no hard dependency on the extra.

The ADK transport defaults to streamable HTTP, so the ``pagila-support-mcp`` server must be
running. ADK degrades *silently* when it can't reach the server (the specialist simply sees
no tools), which would surface as a confusing "I don't have that tool" reply. To make the
failure legible we pre-flight the connection and return a clear 503 with the command to
start it. The exception path is kept as a fallback (e.g. for the stdio transport).
"""

from __future__ import annotations

from urllib.parse import urlsplit

import anyio
import httpx
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from adk_agents.runner import run_query, stream_query
from adk_agents.schemas import AdkChatRequest, AdkChatResult
from app.config import get_settings

router = APIRouter(tags=["adk"])

# Connection-level failures that mean "the MCP server isn't up", including the case where
# ADK surfaces them wrapped in an ExceptionGroup from its task group.
_CONNECTION_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout, ConnectionError, OSError)


def _is_connection_error(exc: BaseException) -> bool:
    if isinstance(exc, _CONNECTION_ERRORS):
        return True
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_connection_error(inner) for inner in exc.exceptions)
    return False


async def _mcp_http_reachable(url: str, timeout: float = 2.0) -> bool:
    """True if a TCP connection to the MCP server's host:port succeeds quickly."""
    parts = urlsplit(url)
    host = parts.hostname or "127.0.0.1"
    port = parts.port or (443 if parts.scheme == "https" else 80)
    try:
        with anyio.fail_after(timeout):
            stream = await anyio.connect_tcp(host, port)
            await stream.aclose()
        return True
    except (OSError, TimeoutError):
        return False


def _server_down(detail_url: str) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            f"The pagila-support-mcp server is unreachable at {detail_url}. "
            "Start it with: uv run python -m app.mcp.server --http"
        ),
    )


@router.post("/adk/respond", response_model=AdkChatResult)
async def adk_respond(request: AdkChatRequest) -> AdkChatResult:
    """Run the message through the ADK coordinator and return its reply."""
    settings = get_settings()
    if settings.adk_mcp_transport == "http" and not await _mcp_http_reachable(
        settings.adk_mcp_url
    ):
        raise _server_down(settings.adk_mcp_url)

    try:
        return await run_query(
            request.message, request.customer_id, request.conversation_id
        )
    except Exception as exc:  # noqa: BLE001 -- classify, then re-raise non-connection errors
        if _is_connection_error(exc):
            raise _server_down(settings.adk_mcp_url) from exc
        raise


@router.post("/adk/respond/stream")
async def adk_respond_stream(request: AdkChatRequest) -> StreamingResponse:
    """Same as /adk/respond, streamed: NDJSON chunk/blocked/done events with chunk-level
    output validation (cuts over to a safe reply if a guardrail trips mid-stream)."""
    settings = get_settings()
    if settings.adk_mcp_transport == "http" and not await _mcp_http_reachable(
        settings.adk_mcp_url
    ):
        raise _server_down(settings.adk_mcp_url)
    return StreamingResponse(
        stream_query(request.message, request.customer_id, request.conversation_id),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
