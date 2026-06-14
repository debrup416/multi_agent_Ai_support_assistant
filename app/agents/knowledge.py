"""KnowledgeAgent — general support / how-to, grounded in the local KB.

Also serves as the low-confidence fallback agent (the orchestrator routes ambiguous
messages here with ``next_action="clarify"``).
"""

from __future__ import annotations

from app.llm.base import LLMClient
from app.schemas.contracts import AgentContext, AgentResult, Citation
from app.schemas.tools import KbQuery
from app.tools import invoke
from app.tools.registry import SEARCH_KB

SYSTEM = """You are the knowledge-base support specialist. Answer ONLY from the provided KB \
articles and cite them. If the articles do not contain the answer, say clearly that you could not \
find it in the knowledge base — do not guess. Be concise and courteous."""


class KnowledgeAgent:
    name = "KnowledgeAgent"
    responsibility = "General support / how-to questions, grounded in the local KB."
    tool_names = [SEARCH_KB.name]

    def handle(self, ctx: AgentContext, llm: LLMClient) -> AgentResult:
        result = invoke(SEARCH_KB, KbQuery(query=ctx.request.message))
        tool = SEARCH_KB.name

        if not result.found:
            answer = llm.complete(
                system=SYSTEM,
                prompt=f'Customer asked: "{ctx.request.message}". The knowledge base has no '
                f"matching article. Tell them you could not find an answer in the KB.",
            )
            return AgentResult(answer=answer, tools_used=[tool], citations=[])

        articles = "\n\n".join(
            f"[{a.id}] {a.title}\n{a.snippet}" for a in result.results
        )
        answer = llm.complete(
            system=SYSTEM,
            prompt=f'Customer asked: "{ctx.request.message}"\n\nKB articles:\n{articles}\n\n'
            f"Answer using only these articles and reference the relevant article id.",
        )
        citations = [
            Citation(source=a.id, snippet=a.title) for a in result.results
        ]
        return AgentResult(answer=answer, tools_used=[tool], citations=citations)
