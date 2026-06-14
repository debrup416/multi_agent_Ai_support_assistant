# Project Understanding — Multi-Agent AI Support Assistant

> My (Claude's) working understanding of this project as of 2026-06-13, captured from
> `docs/design.md` and `docs/implementation_plan.md`. This is a reference snapshot, not
> a spec — `design.md` remains the authority on architecture.

## What this is

A take-home assignment (Netsol Gen AI CoE) building a **multi-agent AI support assistant**
for a fictional **streaming + rental** platform. The service exposes a single HTTP endpoint,
`POST /agent/respond`, which:

1. Accepts a customer message (`customer_id`, `conversation_id`, `message`).
2. Runs an **input guardrail** (injection / sensitive-mutation / missing-id screening).
3. **Triages** the message — an LLM classifier picks an intent + specialist agent + confidence.
4. **Routes** deterministically to one specialist agent via a registry (not LLM-chosen dispatch).
5. The agent calls **typed, DB-backed tools** to answer from real data.
6. Runs an **output guardrail** (schema / data-exposure / grounding / tone).
7. Returns a **stable, validated JSON contract** (`AgentResponse`).

Backed by the **Pagila** Postgres sample DB plus 2 Alembic migrations.

## Core design principles

- **No single giant prompt** — each agent has a narrow job and a small prompt.
- **Deterministic scaffolding, LLM only where it earns its place** — routing, SQL, schema
  validation, safety rules are plain code; the LLM does classification, NL answering, and a
  final tone/grounding review.
- **Typed contracts at every boundary** — request, response, agent results, and every tool's
  in/out are Pydantic models. Malformed LLM output is repaired (bounded loop) or fails closed.
- **Truthful grounding** — agents answer only from tool results + local KB; cite or say "none".
- **Safe by construction** — DB tools are read-only; mutations are blocked or escalated to a
  human handoff. The agent layer has **no write path** to customer state.

## Architecture layers

```
API (FastAPI)  →  Orchestrator  →  Agents  →  Tools  →  Repository  →  Postgres / KB / mock sink
```

- **API:** FastAPI, request/response validation, correlation id, error envelope.
- **Orchestrator:** input guardrail → triage → router → specialist → output guardrail; owns
  the response build.
- **Agents:** TriageAgent + 5 specialists + a Guardrail reviewer stage.
- **Tools:** typed Pydantic in/out functions, MCP-ready descriptors, per-call structured logging.
- **Repository:** SQLAlchemy, parametrized read-only queries, pool + statement timeout.
- **Data:** Postgres (Pagila + migrations), local KB files, mock handoff sink.
- **Cross-cutting:** provider-swappable `LLMClient`, typed `Settings`, structured logging,
  MCP adapter, retry/timeout.

## Agents & their tools

| Agent | Responsibility | Tool |
|---|---|---|
| TriageAgent | Classify intent, pick specialist | none (classifier) |
| CatalogAgent | Film catalog & streaming availability | `search_film_catalog` |
| SubscriptionAgent | Subscription status & renewal | `get_customer_streaming_subscription` |
| RentalHistoryAgent | Recent rentals | `get_customer_rental_history` |
| KnowledgeAgent | General support / how-to (+ low-confidence fallback) | `search_kb` |
| HumanHandoffAgent | Escalation & risky requests | `create_handoff_ticket` (mock) |
| Guardrail reviewer | Final answer review (always runs) | none |

Routing is a deterministic `ROUTES` registry keyed by intent; `CONFIDENCE_THRESHOLD = 0.55`
falls back to KnowledgeAgent + `next_action="clarify"`.

## Response contract (the stability promise)

`AgentResponse` fields: `conversation_id`, `intent`, `selected_agent`, `answer`, `confidence`,
`tools_used`, `citations`, `next_action` (answer/clarify/escalate/handoff/block), `guardrail_result`.

## Guardrails (defense in depth)

- **Input (pre-routing):** prompt-injection / system-prompt exfil → safe canned response;
  sensitive-mutation intent (cancel/refund/change-payment) → escalate/handoff, never executed;
  missing/invalid `customer_id` → graceful, no cross-customer leak.
- **Output (pre-return):** schema validation (+ bounded repair loop), data-exposure check,
  grounding/unsupported-claim check, tone check. Result surfaced in `guardrail_result`.

## Database & migrations

- **Migration 1:** `film.streaming_available BOOLEAN NOT NULL DEFAULT FALSE` (backfill some
  titles incl. "Alien" → true).
- **Migration 2:** `streaming_subscription` table (FK → customer) + seed ≥1 row for customer 1.
- Restore sequence: `createdb pagila` → load schema/data → `alembic upgrade head`.
- Rental history joins customer → rental → inventory → film.

## MCP readiness

- Every tool carries `ToolDescriptor` metadata (name, description, input/output JSON schema,
  error behavior, auth requirement, ownership boundary) — the "required for all" bar.
- A `ToolAdapter` seam lets the same `ToolSpec` run in-process today or via an MCP client later.
- **Senior-signal stretch:** a local MCP server `pagila-support-mcp` exposing the DB tools.

## LLM provider abstraction

Thin `LLMClient` interface (`complete`, `complete_structured`) with **Anthropic Claude as
default** and an **OpenAI GPT-mini/nano** swap (assignment-provided key). Provider/model/
thresholds are config. Target tier is mini/nano — which is *why* the system leans on
deterministic routing and tight prompts.

## Implementation plan (phased, 4–6h time box)

P0 scaffolding → P1 DB & migrations → P2 repository & DB tools → P3 LLM client & schemas →
P4 agents/triage/routing → P5 guardrails & orchestrator endpoint → P6 observability →
P7 tests & evals (≥10) → P8 docs polish. **Stretch:** `pagila-support-mcp`, tracing/cost logs,
Docker Compose, retries/timeouts.

## Current state (as of this snapshot)

- `docs/design.md` and `docs/implementation_plan.md` — complete and detailed.
- `docs/ai_usage.md` — present (not yet read in detail).
- `.venv` exists (`uv venv`); **no application code written yet** — repo layout under `app/`,
  `mcp/`, `migrations/`, `kb/`, `evals/`, `tests/` is intended but not yet created.
- Not a git repository yet.

## Known limitations (acknowledged in the plan)

KB retrieval is keyword-based (not RAG); auth is simplified (`customer_id` trusted); handoff is
a mock; mini/nano classification is brittle near the threshold; sync FastAPI to start; eval
coverage is representative not exhaustive; MCP server is stretch; single-node local scope.

## Action item flagged in the design

`design.md` §10 notes the OpenAI key (problem statement) and the Anthropic key currently in
`.env` are **exposed** — rotate both before submission and keep out of version control.
