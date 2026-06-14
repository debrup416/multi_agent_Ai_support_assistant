"""The ``pagila_support`` Semantic Kernel agent package.

Modules:
- ``llm``        — ``LiteLLMChatCompletion``: the SK↔LiteLLM chat-completion connector.
- ``mcp_plugin`` — MCP transport selection + a single-tool plugin per specialist.
- ``specialists``— ``SPECS`` (one bounded agent per MCP tool) + built ``ChatCompletionAgent``s.
- ``agent``      — the tool-less triage agent + ``HandoffOrchestration`` wiring.
- ``guardrails`` — optional Guardrails AI input screen + output filter.

The runnable seam lives one level up in ``sk_agents.runner.run_query``.
"""
