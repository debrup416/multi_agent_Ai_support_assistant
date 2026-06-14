"""CatalogAgent — film catalog & streaming availability."""

from __future__ import annotations

from app.agents.util import extract_search_term
from app.llm.base import LLMClient, StructuredOutputError
from app.schemas.contracts import AgentContext, AgentResult, CatalogSearchTerm, Citation
from app.schemas.tools import FilmCatalogQuery
from app.tools import invoke
from app.tools.registry import SEARCH_FILM_CATALOG

SYSTEM = """You are the catalog specialist for a streaming + rental platform. Answer ONLY from the \
film data provided — never invent titles, prices, or availability. Mention streaming availability, \
category, rating, and rental rate when relevant. If no film is provided, say it was not found. Be \
concise and courteous."""

# The catalog tool does a case-insensitive *title* match, so the search term must be the
# title keyword(s) — not the customer's whole sentence. We let the LLM pull that keyword out
# (e.g. "any movies about dinosaurs?" -> "dinosaur"), the same way the ADK/SK runtimes let the
# model choose the tool argument, and fall back to a deterministic heuristic if it can't.
EXTRACT_SYSTEM = """Extract the film title or keyword to search a movie catalog for, from the \
customer's message. Reply with ONLY the search term (a title or one to three keywords) — strip \
filler like "do you have", "movies", "films", "in the title". If unsure, return the most \
distinctive noun."""


class CatalogAgent:
    name = "CatalogAgent"
    responsibility = "Film catalog & streaming availability questions."
    tool_names = [SEARCH_FILM_CATALOG.name]

    def _search_term(self, message: str, llm: LLMClient) -> str:
        """LLM-extracted title keyword, with the deterministic heuristic as a fallback."""
        try:
            term = llm.complete_structured(
                system=EXTRACT_SYSTEM, prompt=message, schema=CatalogSearchTerm
            ).term.strip()
            if term:
                return term
        except StructuredOutputError:
            pass
        return extract_search_term(message)

    def handle(self, ctx: AgentContext, llm: LLMClient) -> AgentResult:
        term = self._search_term(ctx.request.message, llm)
        result = invoke(SEARCH_FILM_CATALOG, FilmCatalogQuery(query=term))

        if not result.items:
            answer = llm.complete(
                system=SYSTEM,
                prompt=f'The customer asked: "{ctx.request.message}". No film matching '
                f'"{term}" was found in the catalog. Tell them it was not found.',
            )
            return AgentResult(
                answer=answer, tools_used=[SEARCH_FILM_CATALOG.name], citations=[]
            )

        data = "\n".join(
            f"- {i.title} | category={i.category} | rating={i.rating} | "
            f"rental_rate=${i.rental_rate} | streaming_available={i.streaming_available}"
            for i in result.items
        )
        answer = llm.complete(
            system=SYSTEM,
            prompt=f'Customer asked: "{ctx.request.message}"\n\nMatching films:\n{data}\n\n'
            f"Answer the question using only this data.",
        )
        citations = [
            Citation(
                source=SEARCH_FILM_CATALOG.name,
                snippet=f"{result.items[0].title}; streaming_available="
                f"{result.items[0].streaming_available}",
            )
        ]
        return AgentResult(
            answer=answer, tools_used=[SEARCH_FILM_CATALOG.name], citations=citations
        )
