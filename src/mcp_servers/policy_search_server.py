#!/usr/bin/env python
"""Week 9 — server one, "my own": the same policy-document search this app has had since
Week 3, now exposed over MCP instead of imported directly.

    ./.venv/bin/python src/mcp_servers/policy_search_server.py

Runs over stdio (the default transport for a locally-spawned server — see mcp_config.json,
which is what actually starts this process; running it by hand is only for manual testing).

The AI does not run here. This process holds no model, no API key, and calls no LLM — it is
a capability the host's agent invokes, nothing more. See the module docstring in
src/agent/mcp_client.py for exactly where the model call happens instead.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastmcp import FastMCP

from src.agent import tools as native_tools

mcp = FastMCP(name="policy-search")


@mcp.tool
def search_policy(query: str, top_k: int = 3) -> list[dict]:
    """Search the motor own-damage policy wording and its endorsements with a free-text
    query, and return the matching clause text with its document id and effective date.

    Use this to check whether something in an adjuster's notes triggers an exclusion (pass
    the fact pattern as the query, not a claim number), or to find which figure — such as
    the compulsory deductible — is currently in force for a given date of loss, since a
    later endorsement can supersede the base wording. Does not fetch a specific claim's
    facts and does not compute any amount — this server only searches policy documents.
    """
    return native_tools.search_policy(query, top_k=top_k)


if __name__ == "__main__":
    mcp.run()
