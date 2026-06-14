# `adk_agents/` — a Google ADK runtime over the MCP tools

A second agent framework for the same five support tools. Where `app/` runs a deterministic
router + guardrails in-process, this package lets **Google ADK** drive **Claude** over MCP: a
**coordinator** delegates to **five specialists**, each scoped to one tool via an `McpToolset`
`tool_filter`. It adds no tool logic — it connects to the `pagila-support-mcp` server (`app/mcp/`).

## Layout

```
adk_agents/
  pagila_support/        # the ADK agent package (discovered by `adk web` / `adk run`)
    env.py               # loads the repo-root .env so LiteLlm sees the provider API key(s)
    toolsets.py          # transport factory (streamable HTTP | stdio) + make_toolset(tool)
    specialists.py       # SPECS → 5 LlmAgents, one MCP tool each (built from app.tools.REGISTRY)
    agent.py             # root_agent = coordinator with sub_agents=SPECIALISTS
  schemas.py             # AdkChatRequest / AdkChatResult
  runner.py              # run_query(...) — the one seam the route + demo + tests share
  demo.py                # `python -m adk_agents.demo` — sample messages, end-to-end
```

## Run

Requires the optional extra, a reachable MCP server, the migrated Pagila DB, and at least one LLM key
(`ANTHROPIC_API_KEY` or `OPENAI_API_KEY`) in the repo-root `.env` — the provider is auto-detected the
same way as the core path.

```bash
uv sync --extra adk

# 1) Start the tools over streamable HTTP (the default transport for this layer)
uv run python -m app.mcp.server --http --port 8765

# 2) Pick one:
uv run python -m adk_agents.demo     # scripted end-to-end run (live Claude)
uv run adk web adk_agents            # dev UI; choose `pagila_support`, then chat ("my customer id is 1")
# or hit POST /adk/respond on the FastAPI app (uv run uvicorn app.api:app --reload)
```

## Configuration

Reuses the project `Settings` (`app/config.py`):

- The model is resolved from `Settings.litellm_model_string` — provider auto-detected from the
  API keys (`anthropic/<anthropic_model>` or `openai/<openai_model>`, Anthropic preferred when both
  are present), overridable via `LLM_PROVIDER`. Defaults: `anthropic_model=claude-haiku-4-5`,
  `openai_model=gpt-5.4-mini`.
- `adk_mcp_transport` — `http` (default) or `stdio`.
- `adk_mcp_url` — default `http://127.0.0.1:8765/mcp` (used when transport is `http`).

To let ADK launch the MCP server itself instead of connecting to a running one, set
`ADK_MCP_TRANSPORT=stdio`. On Windows the `adk web` reloader can't spawn the stdio subprocess —
run `adk web adk_agents --no-reload`, or just use the default HTTP transport.

## Guardrails (optional — `guardrails` extra)

`guardrails.py` adds a **Guardrails AI** plugin on the ADK `Runner` (`GuardrailPlugin`). One plugin
guards the coordinator and every specialist:

- `before_agent_callback` screens the user message and short-circuits the run — prompt-injection →
  a safe canned reply; cancel/refund/close → a deterministic escalation (how-to questions are *not*
  tripped).
- `after_model_callback` redacts an answer that leaks the system prompt / internal identifiers.

Detectors are Guardrails AI `Guard` + custom `Validator`s; the shipped ones are regex (offline, no
Hub token). Set `ADK_GUARDRAILS_ML_INJECTION=true` to also use the Hub's ML `DetectJailbreak`
validator (`guardrails hub install hub://guardrails/detect_jailbreak`; skipped gracefully if absent).
The plugin is wired via `try/except ImportError`, so without the extra the agents run unguarded.

```bash
uv sync --extra adk --extra guardrails
ADK_GUARDRAILS_ENABLED=true uv run python -m adk_agents.demo   # injection blocked, mutation escalated
```

> **Why Guardrails AI and not LLM Guard?** LLM Guard can't co-install with the ADK layer — it pins
> `transformers==4.51.3` (→ `tokenizers<0.22`) while google-adk's litellm needs `tokenizers==0.22.2`.
> Guardrails AI shares google-adk's litellm range, supports Python 3.13, and doesn't force torch.

## Scope (what this is *not*)

- **Not** a re-implementation of the deterministic router. Routing is LLM-driven (ADK
  `transfer_to_agent`). Guardrails are an optional plugin (above), not the core's pipeline.
- `POST /adk/respond` returns a **leaner** body than `AgentResponse` — no `confidence` /
  `guardrail_result`, because this path produces neither.
- `customer_id` is **trusted, not verified** — the same model as the REST/MCP paths. The runner
  injects it into ADK session state for the customer-scoped specialists.

## Tests

`tests/test_adk_agents.py` covers the wiring (transport factory, specialist↔tool mapping, coordinator
sub-agents, route mounting) with **no network and no LLM** — `McpToolset` builds lazily, so
constructing the agents is offline-safe. The module skips when the `adk` extra isn't installed.
End-to-end runs (live MCP + Claude) are the `demo`, not pytest.
