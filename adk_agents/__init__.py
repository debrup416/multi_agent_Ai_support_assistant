"""A Google ADK multi-agent layer over the ``pagila-support-mcp`` tools.

This is a *second* agent runtime for the same five support tools: where ``app/agents``
runs a deterministic router + guardrails in-process, ``adk_agents`` lets Google ADK drive
Claude over MCP. It adds no tool logic — a coordinator delegates to five specialists, each
bound to one MCP tool (see ``pagila_support/``).

Two ways in, one seam (``runner.run_query``): the FastAPI ``POST /adk/respond`` route and a
runnable ``python -m adk_agents.demo``. The agent package is also discoverable by
``adk web adk_agents`` / ``adk run adk_agents/pagila_support``.
"""
