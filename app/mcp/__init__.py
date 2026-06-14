"""``pagila-support-mcp``: the tool registry exposed over the Model Context Protocol.

A fourth transport alongside in-process and HTTP. The server is a thin wrapper: its
handlers iterate ``app.tools.REGISTRY`` and route calls through the same
``app.tools.invoke`` seam, so an MCP client exercises the identical tool -> service
path the agent and REST routes use.
"""
