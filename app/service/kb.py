"""Local knowledge-base search (keyword-based, not RAG).

KB articles are Markdown files under ``kb/``. Each file's id is its stem, its title is
the first ``# heading`` (or the stem), and the body is searched by token overlap. This
is intentionally simple — the design notes RAG is out of scope — but it returns real
source references so the KnowledgeAgent can cite or honestly say it found nothing.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

from app.config import get_settings
from app.schemas.tools import KbArticle, KbResult

KB_DIR = Path(__file__).resolve().parents[2] / "kb"
_WORD_RE = re.compile(r"[a-z0-9]+")


class _Article:
    __slots__ = ("id", "title", "body", "tokens")

    def __init__(self, id: str, title: str, body: str) -> None:
        self.id = id
        self.title = title
        self.body = body
        self.tokens = set(_WORD_RE.findall(f"{title}\n{body}".lower()))


@lru_cache
def _load_articles() -> list[_Article]:
    articles: list[_Article] = []
    if not KB_DIR.is_dir():
        return articles
    for path in sorted(KB_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        first = text.splitlines()[0].strip() if text.strip() else ""
        title = first.lstrip("# ").strip() if first.startswith("#") else path.stem
        articles.append(_Article(id=path.stem, title=title, body=text))
    return articles


def _snippet(body: str, terms: set[str], length: int = 200) -> str:
    """A short excerpt around the first matching term (falls back to the top)."""
    lower = body.lower()
    pos = min((lower.find(t) for t in terms if t in lower), default=-1)
    if pos < 0:
        excerpt = body.strip()[:length]
    else:
        start = max(0, pos - 40)
        excerpt = body[start : start + length].strip()
    return re.sub(r"\s+", " ", excerpt)


def search_kb(query: str, limit: int | None = None) -> KbResult:
    """Return KB articles ranked by token overlap with the query."""
    limit = limit if limit is not None else get_settings().kb_result_limit
    terms = set(_WORD_RE.findall(query.lower()))
    scored: list[tuple[int, _Article]] = []
    for art in _load_articles():
        score = len(terms & art.tokens)
        if score > 0:
            scored.append((score, art))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    top = scored[:limit]
    results = [
        KbArticle(id=art.id, title=art.title, snippet=_snippet(art.body, terms))
        for _, art in top
    ]
    return KbResult(found=bool(results), results=results)


def list_kb_articles() -> list[KbArticle]:
    """All KB articles (id, title, leading snippet) for the ``/kb`` route."""
    return [
        KbArticle(id=a.id, title=a.title, snippet=_snippet(a.body, set()))
        for a in _load_articles()
    ]


def get_kb_article(article_id: str) -> KbArticle | None:
    """One KB article by id, with its full body as the snippet."""
    for art in _load_articles():
        if art.id == article_id:
            return KbArticle(id=art.id, title=art.title, snippet=art.body.strip())
    return None
