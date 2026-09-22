"""Week 9 — MCP servers this app exposes. Each one is a separate process, started by the
agent's MCP client over stdio; neither server ever imports or calls an LLM — see each
module's own docstring for why that boundary is drawn where it is.
"""
