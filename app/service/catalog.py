"""Film catalog search business logic."""

from __future__ import annotations

from app.config import get_settings
from app.repository import connection
from app.repository.queries import search_films
from app.schemas.tools import FilmCatalogItem, FilmCatalogResult


def search_film_catalog(query: str, limit: int | None = None) -> FilmCatalogResult:
    """Search films by title/keyword; report ``truncated`` if more rows existed."""
    limit = limit if limit is not None else get_settings().catalog_result_limit
    with connection() as conn:
        rows = search_films(conn, query=query, limit=limit)
    truncated = len(rows) > limit
    items = [FilmCatalogItem(**row) for row in rows[:limit]]
    return FilmCatalogResult(items=items, truncated=truncated)
