"""A Microsoft Semantic Kernel multi-agent layer over the ``pagila-support-mcp`` tools.

This is a *third* agent runtime for the same five support tools, alongside the core
in-process pipeline (``app/agents``) and the Google ADK layer (``adk_agents``). Where the
core runs a deterministic router and ADK delegates via ``transfer_to_agent``, this layer
uses Semantic Kernel's ``HandoffOrchestration``: a tool-less triage agent hands off to one
of five specialists, each bound to exactly one MCP tool. It adds no tool logic — the only
new LLM plumbing is a thin SK↔LiteLLM connector so every runtime shares one
provider-resolution path (see ``pagila_support/llm.py``).

Two ways in, one seam (``runner.run_query``): the FastAPI ``POST /sk/respond`` route and a
runnable ``python -m sk_agents.demo``. Install with ``uv sync --extra sk`` (plus
``--extra guardrails`` for the optional guardrail layer). The ``sk`` and ``adk`` extras can be
installed together (``uv sync --extra adk --extra sk --extra guardrails``), so both runtimes'
endpoints can be served from one app.
"""
