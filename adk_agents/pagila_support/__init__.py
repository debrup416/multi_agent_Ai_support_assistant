"""The ``pagila_support`` ADK agent package.

``adk web adk_agents`` / ``adk run adk_agents/pagila_support`` discover the agent through
the module-level ``root_agent`` in ``agent.py``; importing it here is the ADK convention.
"""

from . import agent  # noqa: F401

root_agent = agent.root_agent
