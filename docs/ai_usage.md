# AI Usage

A brief, honest account of how AI coding tools were used on this assignment, what they produced,
and what I directed, reviewed, and changed. This is a **living document** — updated through
implementation and finalized at submission. The design docs, the full application (`app/`,
migrations, KB, tests, evals), and this README are now implemented.

## Tools used

- **Claude Code** (Anthropic, Opus 4.8) via the CLI — the only AI tool used. Run in its plan-mode
  workflow: it proposes a plan, I approve or redirect, then it writes. No Cursor, Copilot, or
  Codex were used.

## What it helped with (so far)

- Extracted and structured the requirements from the assignment `.docx`.
- Drafted [`docs/design.md`](./design.md) — architecture, the seven agents, routing/handoff, tool
  contracts, database access, MCP readiness, guardrails, and tradeoffs, with diagrams.
- Drafted [`docs/implementation_plan.md`](./implementation_plan.md) — the phased plan, checklist,
  assumptions, testing approach, and known limitations.

## What I directed / decided

These choices were mine; the AI executed them rather than choosing autonomously:

- **Provider-abstracted LLM** — Claude as default (matching the key in `.env`), OpenAI/GPT-mini as
  a config swap — instead of hardwiring one provider.
- **Framework-free custom orchestration**, with clean seams so a framework (LangGraph / Agents SDK)
  can be slotted in later. Framework choice deliberately deferred to implementation time.
- **MCP at the "senior signal" level** — descriptors on every tool plus a replaceable adapter
  targeting a local `pagila-support-mcp` server.
- **Senior-engineer depth** for the docs (concrete contracts and failure modes over prose).

## What I reviewed / changed

- Cross-checked both docs against the assignment: required response fields, the 7 agents, 5 tools,
  and 2 migrations all match the spec.
- Flagged a security issue the assignment surface introduced: the OpenAI key in the problem
  statement and the Anthropic key in `.env` are **live and exposed**. Decision: all keys via env
  only, `.env` git-ignored, and **rotate both keys before submission**. No key value appears in any
  tracked file.
- Kept the two docs consistent with each other (shared repo layout, contracts, and decisions) to
  avoid architectural drift.

## Implementation — what the AI built and what I verified

AI (Claude Code) implemented the full layered application from `design.md`: the `service` →
`tools` → `api` layering, the SQLAlchemy read-only repository, the five typed tools with MCP
descriptors, the `LLMClient` abstraction (Anthropic adapter + structured-output repair loop +
a fake for tests), the triage classifier, the five specialists and deterministic router, the
input/output guardrails, the orchestrator, the FastAPI operator surface, the KB articles, the
≥10-case eval suite, and the test suite.

The bar held throughout: **nothing submitted that I can't explain.** What I directed/verified:

- **Read-only DB access** — the engine opens `default_transaction_read_only` Postgres sessions, so
  a write attempt fails at the database, not just by convention. All SQL is parametrized and lives
  in one repository module.
- **Caught a real bug** — the initial catalog query fanned out one row per `film_category` link
  (this Pagila variant has several per film); fixed with a correlated subquery so each film returns
  once. Verified against the live DB.
- **Adversarial guardrail behavior** — verified injection is blocked with no prompt leak,
  sensitive mutations escalate to handoff with no state change, and missing `customer_id` degrades
  to a clarify with no tool call (the output guardrail explicitly exempts clarify/handoff from the
  grounding-requires-tools rule).
- **Verification** — `pytest` (32 tests across the service, tool, guardrail, agent, migration, and
  API-contract seams) is green, and the eval runner reports **10/10** against the live model.

Model choice (Claude Haiku 4.5) and the LLM API usage were validated against the current Anthropic
SDK docs rather than written from memory.
