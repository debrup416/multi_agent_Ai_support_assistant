"""FastAPI application factory.

Mounts the core graded endpoint plus the read-mostly operator surface (introspection,
per-tool invocation, triage debug, KB/handoff browsing, eval runner, config), and serves
the zero-build static web UI at ``/ui``. Run with ``uvicorn app.api:app``.
"""

from __future__ import annotations

import logging
import mimetypes
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    agent,
    agents_meta,
    capabilities,
    config_route,
    evals_route,
    handoffs,
    health,
    kb,
    tools,
    triage,
)
from app.config import get_settings
from app.observability import tracing
from app.observability.logging import configure_logging

# The static frontend bundle (index.html, styles.css, js/) lives at the repo root: web/.
# main.py is app/api/main.py, so parents[2] is the project root.
_WEB_DIR = Path(__file__).resolve().parents[2] / "web"


@asynccontextmanager
async def _lifespan(_: FastAPI):
    """Flush buffered Langfuse traces on shutdown (no-op when observability is off)."""
    yield
    tracing.shutdown()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level)
    tracing.init_observability(settings)

    app = FastAPI(
        title="Multi-Agent AI Support Assistant",
        version="0.1.0",
        description=(
            "Support assistant for a streaming + rental platform. Core endpoint: "
            "POST /agent/respond. Plus an operator surface for inspecting and exercising "
            "the fixed agents and tools, and a web UI at /ui."
        ),
        lifespan=_lifespan,
    )

    # Core (graded) + operator surface.
    app.include_router(health.router)
    app.include_router(agent.router)
    app.include_router(tools.router)
    app.include_router(agents_meta.router)
    app.include_router(triage.router)
    app.include_router(kb.router)
    app.include_router(handoffs.router)
    app.include_router(evals_route.router)
    app.include_router(config_route.router)
    app.include_router(capabilities.router)

    # Which agent runtimes are live. The UI reads this via /capabilities to build its
    # runtime switcher; "core" is always present, the optional layers append themselves.
    runtimes = ["core"]

    # Optional Google ADK agent layer (`uv sync --extra adk`). Mounted only when the extra
    # is installed, so the core API carries no hard dependency on google-adk / litellm.
    try:
        from app.api.routes import adk_route
    except ImportError:
        logging.getLogger("api").info(
            "ADK endpoint not mounted (google-adk not installed; `uv sync --extra adk`)."
        )
    else:
        app.include_router(adk_route.router)
        runtimes.append("adk")

    # Optional Semantic Kernel agent layer (`uv sync --extra sk`). Same conditional mount; `sk`
    # and `adk` can be installed together, so both `/adk/respond` and `/sk/respond` may mount.
    try:
        from app.api.routes import sk_route
    except ImportError:
        logging.getLogger("api").info(
            "SK endpoint not mounted (semantic-kernel not installed; `uv sync --extra sk`)."
        )
    else:
        app.include_router(sk_route.router)
        runtimes.append("sk")

    app.state.runtimes = runtimes

    # --- Static web UI --------------------------------------------------------
    # Serve the frontend same-origin (no CORS needed). On Windows, StaticFiles derives
    # content types from the registry, where `.js` is frequently registered as text/plain —
    # browsers then refuse to load `<script type="module">` (strict MIME). Pin the JS types
    # so native ES modules load regardless of the host machine's registry.
    mimetypes.add_type("text/javascript", ".js")
    mimetypes.add_type("text/javascript", ".mjs")
    if _WEB_DIR.is_dir():
        app.mount("/ui", StaticFiles(directory=str(_WEB_DIR), html=True), name="ui")

        @app.get("/", include_in_schema=False)
        def _root_redirect() -> RedirectResponse:
            """Land visitors on the web UI."""
            return RedirectResponse(url="/ui/")

    return app


app = create_app()
