"""FastAPI app entrypoint. ``uvicorn app.api:app``."""

from app.api.main import app, create_app

__all__ = ["app", "create_app"]
