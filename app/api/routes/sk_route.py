"""Optional endpoint: POST /sk/respond — the Semantic Kernel agent layer over HTTP.

A parallel to ``POST /agent/respond`` and ``POST /adk/respond``: same request shape, but the
answer is produced by the Semantic Kernel handoff orchestration (``sk_agents``) driving the
LLM over MCP, not by the deterministic pipeline. Importing this module pulls in
``semantic-kernel``; ``app/api/main.py`` includes it inside a ``try/except ImportError`` so the
core API has no hard dependency on the extra.

The SK transport defaults to streamable HTTP, so the ``pagila-support-mcp`` server must be
running. To make a down server legible we pre-flight the connection and return a clear 503 with
the command to start it; the exception path is kept as a fallback (e.g. for the stdio transport).
"""

from __future__ import annotations

from urllib.parse import urlsplit

import anyio
import httpx
from fastapi import APIRouter, HTTPException

from app.config import get_settings
from sk_agents.runner import run_query
from sk_agents.schemas import SkChatRequest, SkChatResult

router = APIRouter(tags=["sk"])

# Connection-level failures that mean "the MCP server isn't up", including the case where
# SK surfaces them wrapped in an ExceptionGroup from its task group / runtime.
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


@router.post("/sk/respond", response_model=SkChatResult)
async def sk_respond(request: SkChatRequest) -> SkChatResult:
    """Run the message through the Semantic Kernel orchestration and return its reply."""
    settings = get_settings()
    if settings.sk_mcp_transport == "http" and not await _mcp_http_reachable(
        settings.sk_mcp_url
    ):
        raise _server_down(settings.sk_mcp_url)

    try:
        return await run_query(
            request.message, request.customer_id, request.conversation_id
        )
    except Exception as exc:  # noqa: BLE001 -- classify, then re-raise non-connection errors
        if _is_connection_error(exc):
            raise _server_down(settings.sk_mcp_url) from exc
        raise
