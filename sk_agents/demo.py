"""End-to-end demo: ``python -m sk_agents.demo``.

Runs a handful of representative messages through the Semantic Kernel handoff orchestration
and prints each reply, the specialist that handled it, and the MCP tools it called. This is a
*live* run: it needs the MCP server reachable (streamable HTTP by default — start it with
``uv run python -m app.mcp.server --http``), the migrated Pagila DB, and a working LLM key
(``ANTHROPIC_API_KEY`` or ``OPENAI_API_KEY``). It is intentionally not a pytest test
(network + LLM cost).
"""

from __future__ import annotations

import sys

import anyio

from sk_agents.runner import aclose, run_query

# (customer_id, message) — mirrors the ADK demo so the two runtimes are easy to compare.
SAMPLES: list[tuple[int | None, str]] = [
    (1, "Is Alien available for streaming?"),
    (1, "What are my last 3 rentals?"),
    (1, "Is my subscription active?"),
    (None, "How do I update my payment method?"),
    (1, "I want to cancel my subscription right now."),
]


async def _main() -> None:
    try:
        for i, (customer_id, message) in enumerate(SAMPLES, start=1):
            result = await run_query(message, customer_id, conversation_id=f"demo-{i}")
            print(f"\n[{i}] customer_id={customer_id}  {message!r}")
            print(f"    -> agent={result.selected_agent}  tools={result.tools_used}")
            print(f"    {result.reply}")
    finally:
        await aclose()


def main() -> None:
    # Windows consoles default to cp1252; agent replies may contain Unicode (e.g. ✓), so make
    # stdout UTF-8-safe rather than let a print() raise UnicodeEncodeError.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 -- best-effort; non-Windows / non-reconfigurable streams
        pass
    anyio.run(_main)


if __name__ == "__main__":
    main()
