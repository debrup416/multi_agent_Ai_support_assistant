"""CLI eval runner: `python -m evals` (or `uv run python -m evals`).

Runs every case through the real pipeline (live LLM) and prints a pass/fail table.
Exits non-zero if any case fails, so it can gate CI.
"""

from __future__ import annotations

import sys

from evals.runner import run_evals


def main() -> int:
    report = run_evals()
    print(f"\nEval results: {report['passed']}/{report['total']} passed\n")
    print(f"{'RESULT':6}  {'CASE':32}  {'AGENT':18}  {'NEXT':9}  TOOLS")
    print("-" * 90)
    for r in report["results"]:
        flag = "PASS" if r["passed"] else "FAIL"
        print(
            f"{flag:6}  {r['name']:32}  {r['selected_agent']:18}  "
            f"{r['next_action']:9}  {','.join(r['tools_used']) or '-'}"
        )
        if not r["passed"]:
            failing = {k: v for k, v in r["checks"].items() if not v}
            print(f"        failing checks: {failing}")
    print()
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
