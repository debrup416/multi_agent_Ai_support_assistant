"""Load the repo-root ``.env`` so the ADK runtime sees ``ANTHROPIC_API_KEY``.

``pydantic-settings`` reads ``.env`` into the ``Settings`` object, but LiteLlm (which ADK
uses for Claude) reads the key straight from ``os.environ``. The ADK CLI also only
auto-loads a ``.env`` sitting *inside* the agent package. Rather than duplicate secrets,
we load the single source — the repo-root ``.env`` — into the process environment. Import
this module before constructing any LiteLlm-backed agent.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

# adk_agents/pagila_support/env.py -> parents[2] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# `override=False`: a real environment variable always wins over the .env file.
load_dotenv(_REPO_ROOT / ".env", override=False)
