"""The ``pagila-support-mcp`` low-level MCP server.

`list_tools` advertises every registry tool with the JSON Schemas already carried by
its ``ToolDescriptor``; nothing here re-declares a contract. The module-level
``server`` is what both the stdio and streamable-HTTP runners (added below) drive.
"""

from __future__ import annotations

import argparse
import sys

import mcp.types as types
from mcp.server.lowlevel import Server

from app.config import get_settings
from app.observability import tracing
from app.observability.logging import configure_logging
from app.tools import REGISTRY, get_tool, invoke

server = Server("pagila-support-mcp")


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    """Expose every registry tool as an MCP tool, input and output schemas included."""
    tools: list[types.Tool] = []
    for spec in REGISTRY.values():
        descriptor = spec.descriptor()
        tools.append(
            types.Tool(
                name=descriptor.name,
                description=descriptor.description,
                inputSchema=descriptor.input_schema,
                outputSchema=descriptor.output_schema,
            )
        )
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> dict:
    """Run one tool and return its typed result as structured content.

    The SDK has already validated ``arguments`` against the tool's ``inputSchema``;
    ``invoke`` validates again into the typed model, runs the service, and logs the
    call. Returning a dict makes the SDK emit it as ``structuredContent`` plus a JSON
    text block and validate it against the tool's ``outputSchema``.
    """
    spec = get_tool(name)
    if spec is None:
        raise ValueError(f"Unknown tool: {name}")
    result = invoke(spec, arguments)
    return result.model_dump(mode="json")


# --- transports ---------------------------------------------------------------


def _run_stdio() -> None:
    """Serve over stdio (the default).

    stdout carries the JSON-RPC protocol, so logging is routed to stderr.
    """
    import atexit

    import anyio
    from mcp.server.stdio import stdio_server

    configure_logging(get_settings().log_level, stream=sys.stderr)
    tracing.init_observability(get_settings())
    # stdio has no clean shutdown hook; flush traces on process exit.
    atexit.register(tracing.shutdown)

    async def _serve() -> None:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())

    anyio.run(_serve)


def _run_http(host: str, port: int) -> None:
    """Serve streamable HTTP at ``/mcp``, driven by the same ``server`` object."""
    import contextlib
    from collections.abc import AsyncIterator

    import uvicorn
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.routing import Mount
    from starlette.types import Receive, Scope, Send

    configure_logging(get_settings().log_level)
    tracing.init_observability(get_settings())
    manager = StreamableHTTPSessionManager(app=server)

    async def handle(scope: Scope, receive: Receive, send: Send) -> None:
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            try:
                yield
            finally:
                tracing.shutdown()

    app = Starlette(routes=[Mount("/mcp", app=handle)], lifespan=lifespan)
    uvicorn.run(app, host=host, port=port)


def main() -> None:
    """Entry point: ``python -m app.mcp.server`` (stdio) or ``--http`` for HTTP."""
    parser = argparse.ArgumentParser(prog="pagila-support-mcp")
    parser.add_argument(
        "--http", action="store_true", help="serve streamable HTTP instead of stdio"
    )
    parser.add_argument("--host", default="127.0.0.1", help="HTTP bind host (with --http)")
    parser.add_argument("--port", type=int, default=8765, help="HTTP bind port (with --http)")
    args = parser.parse_args()
    if args.http:
        _run_http(args.host, args.port)
    else:
        _run_stdio()


if __name__ == "__main__":
    main()
