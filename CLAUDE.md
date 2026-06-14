# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
uv sync                                   # install deps (runtime + dev) into .venv
docker compose up -d                      # start Postgres; auto-loads db/pagila/{01-schema,02-data}.sql on first boot
uv run alembic upgrade head               # apply the 2 migrations on top of Pagila
uv run uvicorn app.api:app --reload       # serve on :8000 (Swagger at /docs)
uv run python -m app.mcp.server           # pagila-support-mcp over stdio (add --http [--port 8765] for streamable HTTP)

uv sync --extra adk                       # also install the optional Google ADK agent layer (adk_agents/)
uv sync --extra adk --extra guardrails    # ...plus the Guardrails AI guardrail plugin (adk_agents/guardrails.py)
uv run python -m app.mcp.server --http    # ADK uses streamable HTTP by default — start the MCP server first, then:
uv run python -m adk_agents.demo          # run sample messages through the ADK coordinator (LIVE LLM + MCP)
uv run adk web adk_agents                 # ADK dev UI; pick the `pagila_support` agent (chat: "my customer id is 1")

uv sync --extra sk --extra guardrails     # the third runtime: Semantic Kernel layer (sk_agents/) + guardrails
uv run python -m sk_agents.demo           # run sample messages through the SK handoff orchestration (LIVE LLM + MCP)
uv sync --extra adk --extra sk --extra guardrails  # install BOTH runtimes together — /adk/respond + /sk/respond both mount
# (sk>=1.43 + google-adk coexist on pydantic 2.12/2.13; the `sk` extra declares the pre-release azure-ai-agents directly.)

# Optional self-hosted Langfuse observability (traces + token/cost; off unless enabled).
uv sync --extra observability             # install the Langfuse SDK (adk/sk/observability all combinable)
cp .env.langfuse.example .env.langfuse    # then `openssl rand -hex 32` for the 3 secrets
docker compose -f docker-compose.langfuse.yml --env-file .env.langfuse up -d  # 6-container stack on :3000
# then set LANGFUSE_ENABLED=true + LANGFUSE_PUBLIC_KEY/SECRET_KEY (from the UI) + LANGFUSE_HOST in .env

uv run pytest                             # full suite (LLM faked; no network)
uv run pytest tests/test_agents.py -q     # one file
uv run pytest tests/test_agents.py::test_low_confidence_falls_back_to_knowledge_clarify  # one test
uv run python -m evals                    # run the ≥10 eval cases through the real pipeline (LIVE LLM), print a table
```

`pytest`, the migration tests, and the service/tool tests **require a running, migrated Pagila DB**
(they query live Postgres). Re-restore from scratch: `docker compose down -v && docker compose up -d && uv run alembic upgrade head`.

Config comes from `.env` (git-ignored): `DATABASE_URL` plus at least one LLM key. The provider is
**auto-detected from which key is present** — `ANTHROPIC_API_KEY` → Anthropic, else `OPENAI_API_KEY`
→ OpenAI (Anthropic wins when both are set), overridable with `LLM_PROVIDER`. Every provider goes
through one **LiteLLM-backed** `LLMClient` (`app/llm/litellm_client.py`); per-provider models are
config (`anthropic_model` default `claude-haiku-4-5`, `openai_model` default `gpt-5.4-mini`). The
design targets a small/fast tier — validate any SDK / model id changes against current docs, not
memory.

## Architecture

A customer message flows through one pipeline, owned end to end by `app/orchestrator/orchestrator.py`:

```
input guardrail → triage (LLM) → deterministic router → specialist agent → output guardrail → AgentResponse
```

The single source of truth for data access is the **three-layer stack**, and understanding it is key
to working here:

- **`app/service/`** — pure business logic (SQL via repository, KB file search, mock handoff sink).
  Returns typed result models; no Pydantic-tool or HTTP framing leaks in.
- **`app/tools/`** — thin typed wrappers (Pydantic in/out + `ToolDescriptor`) over the service.
  Agents bind to these and call them **in-process** via `app/tools/adapter.py::invoke` (which does
  per-call structured logging). This is the only place that touches the outside world for agents.
- **`app/api/routes/tools.py`** — explicit REST route per tool that delegates to the **same tools
  wrapper**, so a Swagger call exercises the identical path the agent uses.

Same logic, three transports (agent in-process / HTTP / MCP via `app/mcp/server.py`). When changing
a tool's behavior, change `service/`; the tool wrapper, REST route, and MCP server are pass-throughs.

**Second runtime (optional): `adk_agents/`.** A Google ADK multi-agent layer *consumes* the same
tools over MCP — a coordinator delegates to five specialists, each bound to one tool via an
`McpToolset` `tool_filter`. It is gated behind the `adk` extra and a conditional mount, so the core
API has no dependency on it. Deliberately it does **not** re-implement the
deterministic router (ADK delegates via the LLM), and `POST /adk/respond` returns a leaner shape than
`AgentResponse` (no faked `confidence`/`guardrail_result`). Same `customer_id` trust model as the
REST/MCP paths. Guardrails are an **optional** layer (`guardrails` extra): a Guardrails AI plugin
(`adk_agents/guardrails.py`) on the ADK `Runner` — input block/escalate via `before_agent_callback`,
output redaction via `after_model_callback`. See `adk_agents/README.md` and `docs/design.md` §7.1–7.2.

### Conventions and invariants (non-obvious)

- **Routing is deterministic.** The LLM only classifies (`TriageDecision`); dispatch is a dict
  lookup in `app/agents/registry.py::ROUTES`. The `Intent` literal in `app/schemas/contracts.py`
  must stay in lockstep with `ROUTES` keys and the triage system prompt in `app/agents/triage.py`.
  Confidence `< settings.confidence_threshold` falls back to `KnowledgeAgent` with `next_action="clarify"`.
- **The DB is read-only by construction.** `app/repository/engine.py` opens
  `default_transaction_read_only` sessions, so a write attempt fails at Postgres, not by convention.
  Alembic uses its own engine. Only `create_handoff_ticket` "writes" — to an in-process mock sink.
- **Tools never call the LLM or other tools.** No hidden chains.
- **Safety is rule-based first.** `app/guardrails/input_guard.py` blocks prompt-injection (safe
  canned answer) and escalates sensitive mutations (cancel/refund/close → `HumanHandoffAgent`)
  *before* triage runs — the LLM is never trusted with these. Keep mutation patterns narrow so
  how-to questions ("how do I update my payment method?") still route to `KnowledgeAgent`.
- **Output grounding check exempts non-answers.** `app/guardrails/output_guard.py` only blocks a
  data-backed answer for missing tool evidence when `next_action == "answer"` — clarify / handoff /
  block legitimately have no tools. Don't reintroduce the blanket check.
- **Agents are stateless.** `handle(ctx, llm)` receives the `LLMClient`; never construct a client
  inside an agent. Tests pass `app/llm/fake.py::FakeLLMClient` with canned `TriageDecision`/completions.
- **`AgentResponse` is the stability contract.** Every field is required and validated on the way
  out; the API-contract test asserts the full shape.
- Adding a capability = new bounded agent + tool + route entry, never growing a mega-prompt.

The intended architecture and rationale live in `docs/design.md`; the phased plan, testing approach,
and known limitations in `docs/implementation_plan.md`. `docs/` is treated as authoritative — keep it
reconciled with behavior when you change the system.
