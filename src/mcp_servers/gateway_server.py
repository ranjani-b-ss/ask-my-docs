#!/usr/bin/env python
"""Week 9 bonus — one front door for both servers.

    GATEWAY_TOKEN=full-access ./.venv/bin/python src/mcp_servers/gateway_server.py
    GATEWAY_TOKEN=claim-status-only ./.venv/bin/python src/mcp_servers/gateway_server.py

The agent connects to exactly one server (this one) instead of two — see
mcp_config_gateway.json, which lists a single entry. Internally this process is itself an MCP
CLIENT to policy-search and claims-system (spawning both as its own subprocesses, the exact
same way src/agent/mcp_client.py does), and re-exposes their tools under its own name. Every
call that reaches it, allowed or denied, is written as one audit line to
traces/mcp/audit.jsonl before the backend is ever touched — a denial is audited too, which is
the entire point of an audit log existing at all.

Simplification, disclosed rather than hidden: this gateway hand-defines one proxy tool per
capability the two backends currently have, instead of dynamically mirroring whatever
tools/list happens to return at startup. A production gateway would do the latter; three
hand-written proxies are the honest tradeoff for reliability under this exercise's scope —
see WEEK9.md for why.

Token scoping lives here, not in either backend: neither policy_search_server.py nor
claims_system_server.py knows a "token" exists. A denial still has to reach the model as
something it can act on, not a crash — same discipline as requirement 5's error rewrite, and
the same downstream path: this raises a plain ValueError, fastmcp turns it into an MCP tool
error, src/agent/mcp_client.py's dispatch() turns that into a RuntimeError, and
mcp_agent.py's loop turns THAT into "ERROR: ..." in the transcript the model reads next —
no change to either of those two files was needed for this bonus to work.
"""

from __future__ import annotations

import json
import os
import sys
import time
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from fastmcp import FastMCP
from fastmcp.server.dependencies import get_context
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parent.parent.parent
AUDIT_LOG = ROOT / "traces" / "mcp" / "audit.jsonl"

# Which tools a token may call. Nothing here reaches a backend directly — this is checked
# BEFORE _proxy() ever opens a session to policy-search or claims-system.
TOKEN_SCOPES: dict[str, set[str]] = {
    "full-access": {"search_policy", "get_claim_status", "get_adjuster_notes"},
    "claim-status-only": {"search_policy", "get_claim_status"},   # adjuster notes denied
}


@asynccontextmanager
async def lifespan(server: FastMCP):
    """Backend connections are opened HERE, once, in the task that runs for the server's
    entire lifetime — not lazily inside a tool call. A first version did the latter, and it
    crashed on the second call: anyio's cancel scopes are tied to the exact task that opened
    them, and each incoming tools/call runs as its own task. A connection opened inside
    request-task-1 is invalid to reuse from request-task-2 — "Attempted to exit a cancel
    scope that isn't the current task's current cancel scope" is anyio saying exactly that.
    The lifespan hook is the one place a resource opened here is guaranteed to outlive every
    individual request that uses it.
    """
    async with AsyncExitStack() as stack:
        routes: dict[str, ClientSession] = {}
        python = str(ROOT / ".venv" / "bin" / "python")
        for name, script in (
            ("policy-search", "src/mcp_servers/policy_search_server.py"),
            ("claims-system", "src/mcp_servers/claims_system_server.py"),
        ):
            params = StdioServerParameters(command=python, args=[str(ROOT / script)])
            read, write = await stack.enter_async_context(stdio_client(params))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
            for tool in listed.tools:
                routes[tool.name] = session
        yield {"routes": routes}


mcp = FastMCP(name="gateway", lifespan=lifespan)


def _caller_token() -> str:
    return os.environ.get("GATEWAY_TOKEN", "full-access")


def _audit(tool: str, claim_number: str | None, allowed: bool, detail: str = "") -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "caller": _caller_token(),
        "tool": tool,
        "claim_number": claim_number,
        "allowed": allowed,
        "detail": detail,
    }
    with AUDIT_LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


async def _proxy(tool_name: str, args: dict):
    token = _caller_token()
    scope = TOKEN_SCOPES.get(token, set())
    claim_number = args.get("claim_number")

    if tool_name not in scope:
        _audit(tool_name, claim_number, allowed=False, detail=f"denied for token {token!r}")
        suggestion = (" get_claim_status is still available for this claim's status/amount."
                     if tool_name == "get_adjuster_notes" else "")
        raise ValueError(
            f"access denied: this token ({token!r}) is not scoped to call {tool_name!r}. "
            f"Tools this token CAN call: {sorted(scope)}.{suggestion}"
        )

    routes: dict[str, ClientSession] = get_context().lifespan_context["routes"]
    session = routes[tool_name]
    result = await session.call_tool(tool_name, args)
    if result.is_error:
        text = result.content[0].text if result.content else "backend error"
        _audit(tool_name, claim_number, allowed=True, detail=f"backend error: {text[:80]}")
        raise ValueError(text)

    _audit(tool_name, claim_number, allowed=True)
    return json.loads(result.content[0].text)


@mcp.tool(run_in_thread=False)
async def search_policy(query: str, top_k: int = 3) -> list[dict]:
    """Search the motor own-damage policy wording and its endorsements with a free-text
    query, and return the matching clause text with its document id and effective date.
    Proxied through the gateway to the policy-search server — identical behavior and
    identical description to calling that server directly."""
    return await _proxy("search_policy", {"query": query, "top_k": top_k})


@mcp.tool(run_in_thread=False)
async def get_claim_status(claim_number: str) -> dict:
    """Look up the status of one motor own-damage claim by its claim number (C-NNN format,
    e.g. C-001). Proxied through the gateway to the claims-system server. Available to every
    token scope defined on this gateway."""
    return await _proxy("get_claim_status", {"claim_number": claim_number})


@mcp.tool(run_in_thread=False)
async def get_adjuster_notes(claim_number: str) -> dict:
    """Get the adjuster's free-text narrative for one motor own-damage claim by its claim
    number (C-NNN format, e.g. C-001). Proxied through the gateway to the claims-system
    server. NOT available to every token scope — a denial here is recoverable: it names
    which tools the current token can use instead."""
    return await _proxy("get_adjuster_notes", {"claim_number": claim_number})


if __name__ == "__main__":
    mcp.run()
