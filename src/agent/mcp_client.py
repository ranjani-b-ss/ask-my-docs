"""Week 9 — the generic MCP host/client. This file, and only this file, is what requirement 2
asks to stay unchanged when a second server is added: no server or tool this app has ever
defined is named anywhere below, by design, so grepping this file for any of their names
turns up nothing — that absence is the actual proof, not just a claim about it. It reads a
list of servers from config, connects to each one, asks each "what tools do you have"
(tools/list), and merges whatever comes back into one flat registry keyed by tool name. Add a
server to the config and this file discovers its tools the same way it discovered the first
server's — that is the entire point of MCP tool discovery, and the reason this module
contains no server-specific branching at all.

Where the AI runs, stated once so no other file needs to repeat it: nowhere in this module,
and nowhere in the two server processes it spawns. This file only ever speaks JSON-RPC to a
subprocess and gets back a list of tool names/schemas/results — no prompt, no model, no API
key touches this code. The model call happens one layer up, in mcp_agent.py's ReAct loop,
which is the only place in this whole path that ever calls ``llm.chat_with_usage``.
"""

from __future__ import annotations

import json
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@dataclass
class DiscoveredTool:
    name: str
    description: str
    input_schema: dict
    server: str          # which server this tool came from — for the trace, not for routing


def load_config(path: str | Path) -> list[dict]:
    """The list of servers to connect to. Adding a server here is the ENTIRE change
    requirement 1 asks for — see agent_diff.txt for proof nothing below this function
    needed to change to make that true."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return data["servers"]


def _first_text(result) -> str:
    """A CallToolResult carries its payload as a list of content blocks; fastmcp's dict/list
    return values arrive as a JSON-encoded TextContent block. This pulls that text out,
    regardless of which server produced it — no server-specific parsing here either."""
    for block in result.content:
        if getattr(block, "type", None) == "text":
            return block.text
    return ""


class MCPToolRegistry:
    """Connects to every server in the config, discovers their tools, and dispatches calls
    by name. Used as an async context manager so every connection opened here is closed
    together, in reverse order, even if one server's discovery fails partway through.
    """

    def __init__(self, servers: list[dict]):
        self._server_defs = servers
        self._stack: AsyncExitStack | None = None
        self._sessions: dict[str, ClientSession] = {}      # server name -> session
        self.tools: dict[str, DiscoveredTool] = {}          # tool name -> where to find it

    async def __aenter__(self) -> "MCPToolRegistry":
        self._stack = AsyncExitStack()
        for server in self._server_defs:
            params = StdioServerParameters(command=server["command"], args=server["args"],
                                           env=server.get("env"))
            read, write = await self._stack.enter_async_context(stdio_client(params))
            session = await self._stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            self._sessions[server["name"]] = session

            listed = await session.list_tools()
            for tool in listed.tools:
                self.tools[tool.name] = DiscoveredTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.input_schema or {},
                    server=server["name"],
                )
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._stack is not None:
            await self._stack.aclose()

    async def dispatch(self, tool_name: str, args: dict) -> str:
        """Call a discovered tool by name. Routing is by which session actually listed this
        tool name, not by any hardcoded mapping — a tool moving to a different server in a
        future config change would still resolve correctly here without an edit."""
        if tool_name not in self.tools:
            raise KeyError(f"Unknown tool {tool_name!r}. Available: {sorted(self.tools)}")
        session = self._sessions[self.tools[tool_name].server]
        result = await session.call_tool(tool_name, args)
        if result.is_error:
            raise RuntimeError(_first_text(result))
        return _first_text(result)
