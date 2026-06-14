"""Browse the local knowledge base."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.schemas.tools import KbArticle
from app.service import get_kb_article, list_kb_articles

router = APIRouter(tags=["knowledge"])


@router.get("/kb", response_model=list[KbArticle])
def kb_list() -> list[KbArticle]:
    """List all KB articles."""
    return list_kb_articles()


@router.get("/kb/{article_id}", response_model=KbArticle)
def kb_get(article_id: str) -> KbArticle:
    """Fetch one KB article by id (full body in the snippet)."""
    article = get_kb_article(article_id)
    if article is None:
        raise HTTPException(status_code=404, detail=f"Unknown KB article: {article_id}")
    return article
