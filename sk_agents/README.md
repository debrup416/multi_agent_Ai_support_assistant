# `sk_agents/` — a Microsoft Semantic Kernel runtime over the MCP tools

A **third** agent framework for the same five support tools (alongside the core `app/` pipeline and
the Google ADK layer). It lets **Semantic Kernel** drive the LLM over MCP: a tool-less **triage
agent** hands off to one of **five specialists** via SK's `HandoffOrchestration`, each specialist
scoped to exactly one MCP tool. It adds no tool logic — it connects to the `pagila-support-mcp`
server (`app/mcp/`). The only new LLM plumbing is a small **SK↔LiteLLM connector**, so every runtime
(core, ADK, SK) drives the model through the same LiteLLM provider-resolution path.

> **Coexistence:** the `sk` and `adk` extras **can be installed together** — `semantic-kernel>=1.43`
> allows `pydantic>=2.0,<2.14` and `google-adk` needs `pydantic>=2.12,<3`, overlapping at pydantic
> 2.12/2.13. SK 1.43 pulls a pre-release `azure-ai-agents`, so the `sk` extra declares it directly
> (uv won't auto-enable a pre-release for a transitive dep). Install both runtimes at once:
> `uv sync --extra adk --extra sk --extra guardrails`.

## Layout

```
sk_agents/
  pagila_support/
    llm.py           # LiteLLMChatCompletion(ChatCompletionClientBase) — the SK↔LiteLLM connector
    mcp_plugin.py    # transport factory (streamable HTTP | stdio) + make_single_tool_plugin(tool)
    specialists.py   # SPECS → 5 ChatCompletionAgents, one MCP tool each (from app.tools.REGISTRY)
    agent.py         # triage agent + build_handoff_topology() (HandoffOrchestration wiring)
    guardrails.py    # optional Guardrails AI input screen + output redaction
  schemas.py         # SkChatRequest / SkChatResult
  runner.py          # run_query(...) — the one seam the route + demo share
  demo.py            # `python -m sk_agents.demo` — sample messages, end-to-end
```

## Run

Requires the optional extra, a reachable MCP server, the migrated Pagila DB, and at least one LLM key
(`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) in the repo-root `.env` — the provider is auto-detected the
same way as the core path.

```bash
uv sync --extra sk                    # (add --extra guardrails for the guardrail layer)

# 1) Start the tools over streamable HTTP (the default transport for this layer)
uv run python -m app.mcp.server --http --port 8765

# 2) Pick one:
uv run python -m sk_agents.demo       # scripted end-to-end run (live LLM)
# or hit POST /sk/respond on the FastAPI app (uv run uvicorn app.api:app --reload)
```

## How the LLM is called — the LiteLLM connector

SK has no built-in LiteLLM connector, so `llm.py` provides one: `LiteLLMChatCompletion` subclasses
SK's `ChatCompletionClientBase` (the maintainer-recommended way to add a custom LLM) and calls
`litellm.acompletion(...)` in-process — the SK equivalent of the core `app/llm/litellm_client.py` and
ADK's `LiteLlm`. Because LiteLLM speaks the OpenAI request/response shape, the connector reuses SK's
`OpenAIChatPromptExecutionSettings` and the stock function-calling callback, and only translates the
LiteLLM response back into SK content types. Function/tool calling works across providers because
LiteLLM maps the OpenAI tool schema to each provider (e.g. Anthropic) for us.

This means the `sk` extra needs **no provider extra** — it reuses the base `litellm` dependency, so
there is no `anthropic`/`openai` SDK pin to clash with the rest of the project.

## Configuration

Reuses the project `Settings` (`app/config.py`):

- The model is resolved from `Settings.litellm_model_string` — provider auto-detected from the API
  keys (`anthropic/<anthropic_model>` or `openai/<openai_model>`, Anthropic preferred when both are
  present), overridable via `LLM_PROVIDER`. Defaults: `anthropic_model=claude-haiku-4-5`,
  `openai_model=gpt-5.4-mini`.
- `sk_mcp_transport` — `http` (default) or `stdio`.
- `sk_mcp_url` — default `http://127.0.0.1:8765/mcp` (used when transport is `http`).
- `sk_guardrails_enabled` — default `true`.

## Single tool per specialist

SK's MCP plugins have **no per-tool filter** (only a boolean `load_tools`), unlike ADK's
`tool_filter`. So each specialist gets its **own** MCP plugin instance, connected and then **pruned**
to its one owned tool (connecting loads every server tool as an attribute on the plugin; we delete the
others before adding it to that specialist's kernel). The result is the same "one bounded agent per
tool" shape, with genuine MCP transport parity with the ADK layer (five live sessions).

## Guardrails (optional — `guardrails` extra)

`guardrails.py` provides **Guardrails AI** `Guard` + `Validator`s with the same posture as the core
and ADK layers, wired the way SK affords:

- **Input** screen (`SkGuardrails.screen_input`), run by the runner *before* any LLM call —
  prompt-injection → a safe canned reply; cancel/refund/close → a deterministic escalation (how-to
  questions are *not* tripped).
- **Output** redaction (`SkGuardrails.redact_output`), run by the runner over the final answer — a
  system-prompt / internal leak → a safe reply. (An SK *function-invocation* filter only sees tool
  calls, never the model's text, so redaction is a runner post-step; the filter is instead used to
  capture which MCP tools were called.)

It is gated behind the `guardrails` extra and `sk_guardrails_enabled`, built via `try/except
ImportError`, so without the extra the agents run unguarded.

```bash
uv sync --extra sk --extra guardrails
uv run python -m sk_agents.demo       # injection blocked, mutation escalated
```

## Scope (what this is *not*)

- **Not** a re-implementation of the deterministic router. Routing is LLM-driven (SK
  `HandoffOrchestration` — the analogue of ADK's `transfer_to_agent`). SK agent orchestration is
  flagged *experimental* upstream, so the `semantic-kernel` version is pinned.
- `POST /sk/respond` returns a **leaner** body than `AgentResponse` — no `confidence` /
  `guardrail_result`, because this path produces neither.
- `customer_id` is **trusted, not verified** — the same model as the REST/MCP/ADK paths. The runner
  composes it into the task message for the customer-scoped specialists (who ask for it if absent).

## Tests

`tests/test_sk_agents.py` covers the wiring (transport factory, specialist↔tool mapping, the LiteLLM
connector, route mounting) and `tests/test_sk_guardrails.py` covers the guardrails — both with **no
network and no LLM**. Unlike ADK's lazy `McpToolset`, SK's MCP plugin connects eagerly (pruning needs
the loaded tool list), so the tests assert the *static* structure and don't build the agents;
end-to-end runs (live MCP + LLM) are the `demo`, not pytest. The modules skip when the `sk` (and
`guardrails`) extras aren't installed.
