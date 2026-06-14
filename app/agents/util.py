"""Small deterministic helpers shared by specialists.

``extract_search_term`` is the deterministic **fallback** for catalog search-term
extraction: ``CatalogAgent`` now asks the LLM for the title keyword (so natural-language
queries like "movies about dinosaurs" work), and drops back to this regex heuristic when
the model is unavailable or returns nothing — keeping the path safe and offline-testable.
"""

from __future__ import annotations

import re

# Question framing words that aren't useful as catalog search terms.
_STOPWORDS = {
    "is", "are", "was", "were", "the", "a", "an", "do", "does", "did", "i", "my",
    "available", "for", "streaming", "stream", "streamable", "to", "watch", "can",
    "movie", "film", "show", "on", "of", "in", "it", "this", "that", "have", "has",
    "you", "your", "me", "please", "tell", "about", "what", "which", "any",
}
_QUOTED = re.compile(r"[\"'‘’“”]([^\"'‘’“”]{2,})[\"'‘’“”]")
_WORD = re.compile(r"[A-Za-z0-9]+")


def extract_search_term(message: str) -> str:
    """Best-effort catalog search term: quoted text if present, else content words."""
    quoted = _QUOTED.search(message)
    if quoted:
        return quoted.group(1).strip()
    words = [w for w in _WORD.findall(message) if w.lower() not in _STOPWORDS]
    term = " ".join(words).strip()
    # Fall back to the raw message if stripping left nothing useful.
    return term or message.strip()
