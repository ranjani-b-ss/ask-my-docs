"""Week 9 — a ReAct agent whose tools come from MCP discovery, not a hardcoded dict.

    ./.venv/bin/python -m src.agent.mcp_agent "your question" --config mcp_config.json

This file is the one requirement 2's diff has to prove is unchanged when a second server is
added to the config: no specific server or tool name appears anywhere below, by design — a
grep for any of them turns up nothing here, which is the actual proof, not a claim about it.
The system prompt is built from whatever ``MCPToolRegistry`` discovered
(src/agent/mcp_client.py); the loop calls whatever tool name the model asks for, by looking
it up in that same discovered registry. Add a server to mcp_config.json and this file's
behavior changes — its source does not.

Where the AI runs, restated here because this is the one place it is actually true: the
``usage.call_llm`` call below is the only model call in this whole path. mcp_client.py and
both server processes it spawns never call an LLM — they only ever answer "here are my
tools" and "here is what that tool returned". This loop is the host; the two MCP processes
are, deliberately, not.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import time

from .mcp_client import MCPToolRegistry, load_config
from .react_agent import _find_json_object
from .usage import UsageAccumulator
from .. import llm

SYSTEM_PROMPT_TEMPLATE = """\
You are an assistant that answers questions using ONLY the tools listed below — every one \
of them was discovered from an MCP server just now, not built into you. Do not answer from \
general knowledge if a tool could answer the question instead.

Tools:

{tool_block}

On every turn, output ONE of the following two things, and nothing else:

Thought: <your reasoning about what to do next>
Action: <one tool name, exactly as listed above>
Action Input: <a single JSON object with that tool's arguments>

Thought: <your reasoning for why you are now done>
Final Answer: <your answer to the user's question, in plain text>

Rules:
1. Call a tool before answering whenever the question needs information you were not given —
   never invent a fact a tool exists to provide.
2. If a tool call fails, read the error message: a well-written error tells you exactly what
   to fix (a format, a missing argument) — try again corrected, do not guess at the answer
   instead.
3. Output exactly one Thought/Action block or one Thought/Final Answer block per turn.
"""

_ACTION_NAME = re.compile(r"Action:\s*([A-Za-z_][A-Za-z0-9_]*)")
_HAS_FINAL = re.compile(r"Final Answer\s*:", re.IGNORECASE)


def _tool_block(tools: dict) -> str:
    lines = []
    for name, tool in tools.items():
        params = json.dumps(tool.input_schema.get("properties", {}))
        lines.append(f"- {name}({params})\n  {tool.description}")
    return "\n".join(lines)


def _parse_lap(raw: str) -> dict:
    if _HAS_FINAL.search(raw):
        idx = raw.find("Final Answer")
        answer = raw[raw.find(":", idx) + 1:].strip()
        return {"kind": "final", "answer": answer}
    name_match = _ACTION_NAME.search(raw)
    if not name_match:
        return {"kind": "malformed", "error": "no 'Final Answer:' and no 'Action:' found"}
    args, err = _find_json_object(raw, "Action Input")
    if args is None:
        return {"kind": "malformed", "error": f"Action Input did not parse: {err}"}
    return {"kind": "action", "tool": name_match.group(1), "args": args}


async def run(question: str, config_path: str, max_iterations: int = 8,
              provider: str | None = None, model: str | None = None) -> dict:
    """Ask one question. Returns the final answer, every lap's trace, and usage — same
    step-visibility discipline as react_agent.py, so a tool call is checkable, not asserted."""
    servers = load_config(config_path)
    usage = UsageAccumulator()
    if provider:
        usage.provider = provider
    if model:
        usage.model = model

    async with MCPToolRegistry(servers) as registry:
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(tool_block=_tool_block(registry.tools))
        transcript = ""
        steps: list[dict] = []
        final_answer = None

        for iteration in range(1, max_iterations + 1):
            user_turn = (
                f"QUESTION\n{question}\n\n"
                f"TRANSCRIPT SO FAR\n{transcript or '(nothing yet)'}\n\n"
                "What is your next Thought and Action, or your Final Answer?"
            )
            raw = usage.call_llm(system_prompt, user_turn)
            parsed = _parse_lap(raw)
            step = {"lap": iteration, "raw_output": raw, "parsed": parsed}

            if parsed["kind"] == "final":
                final_answer = parsed["answer"]
                steps.append(step)
                break

            if parsed["kind"] == "action":
                tool_name, args = parsed["tool"], parsed["args"]
                try:
                    observation = await registry.dispatch(tool_name, args)
                except Exception as exc:                    # noqa: BLE001 — surfaced as text
                    observation = f"ERROR: {exc}"
                step["tool"] = tool_name
                step["tool_args"] = args
                step["observation"] = observation
                steps.append(step)
                transcript += f"{raw.strip()}\nObservation: {observation}\n\n"
                continue

            steps.append(step)
            transcript += (
                f"{raw.strip()}\nObservation: ERROR — {parsed['error']}. Reply with exactly "
                "one Thought/Action/Action Input block or one Thought/Final Answer block.\n\n"
            )

        return {
            "question": question,
            "final_answer": final_answer,
            "iterations": len(steps),
            "usage": usage.as_dict(),
            "steps": steps,
            "tools_discovered": sorted(registry.tools),
        }


def main() -> int:
    ap = argparse.ArgumentParser(description="Ask the MCP-discovered agent one question")
    ap.add_argument("question")
    ap.add_argument("--config", default="mcp_config.json")
    ap.add_argument("--provider", default=None)
    ap.add_argument("--model", default=None)
    args = ap.parse_args()

    result = asyncio.run(run(args.question, args.config, provider=args.provider, model=args.model))
    print(json.dumps(result, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
