"""Week 12 — the integrated claims triage agent.

One entry point's worth of the whole system: the Week 7 hand-built ReAct loop, running against
the date-scoped Week 3-4 retriever, with its tools DISCOVERED over MCP at runtime (Week 9), under
Week 7 budgets, writing Week 11 spans under one trace id that is handed across every hop.

It exists because the earlier loops each had what the other lacked (SEAMS.md S4):
``react_agent.py`` has budgets, a verification gate, usage and prompt versioning but local-only
tools; ``mcp_agent.py`` discovers tools but has no budgets, no versioning and no trace id.

What the model does and does not decide
---------------------------------------
The model chooses search queries, picks which retrieved clauses make an exclusion ARGUABLE, and
writes a short neutral summary. Everything with exactly one right answer is done in code:

* the loss date, product and policy come from the claims system, and the host OVERWRITES any
  value the model passes for them (and for the claim number) — a date filter the code
  enforces, not a hint in the prompt;
* the version of every cited clause (document, version, effective date, "resolved against")
  is read off the retrieved chunk's metadata, never typed by the model;
* the model may only cite chunk ids this run actually retrieved;
* any text of its own that states an outcome is replaced (``src/triage_guard.py``);
* tool order is enforced, and every run ends in ``refer_to_adjuster`` — if the loop ends
  without one, the host makes the referral itself.

There is no coverage decision anywhere in the output. The packet's ``decision`` is ``None``.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .. import claim_files, llm, redact, span_log, triage_guard
from .budgets import Budgets, exceeded
from .mcp_client import MCPToolRegistry, load_config
from .react_agent import _find_json_object
from .usage import UsageAccumulator

ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_CONFIG = ROOT / "mcp_config_capstone.json"
TRIAGE_BUDGETS = Budgets(max_iterations=12, max_tokens=30_000, max_cost_usd=0.03,
                         max_wall_seconds=240.0)

SYSTEM_PROMPT_TEMPLATE = """\
You are a claims TRIAGE assistant for a motor and health insurer. You prepare a claim file for a \
human adjuster. You NEVER decide or state whether a claim is covered, payable, declined or \
approved — the adjuster decides. You surface the facts and the policy wording that applies, and \
you refer the claim to the adjuster.

You have these tools, discovered from the claims systems just now:

{tool_block}

Work in this order:
1. lookup_policy(claim_number) — always first. It returns the policy number, the product, and the \
authoritative date of loss.
2. check_in_force(policy_number, loss_date). If the policy was NOT in force on the loss date, do \
not search wording or fetch limits — go straight to step 5 and quote the reason.
3. search_wording(query, product, loss_date) — one or more times. Look for (a) any exclusion in \
the "What is not covered" clause that the facts make ARGUABLE and (b) wording relevant to the \
adjuster's question. An exclusion rarely uses the claim's own words, so do not build every \
query from the claim's facts: also search for the "What is not covered" section itself and read \
its whole list.
4. get_limits(claim_number) — the deductible (or co-payment), the sub-limits and the policy \
limit. These are three different numbers; do not merge them.
5. refer_to_adjuster(claim_number, reason, flags) — always the last tool call.

On every turn output ONE of the following two things, and nothing else:

Thought: <your reasoning about what to do next>
Action: <one tool name, exactly as listed above>
Action Input: <a single JSON object with that tool's arguments>

Thought: <why you are done>
Final Answer: {{"facts": ["<short neutral fact from the claim narrative>", ...], \
"exclusion_candidates": [{{"chunk_id": "<id from a search_wording result>", "why": "<which facts \
make this exclusion arguable>"}}], "wording_relevant": [{{"chunk_id": "<id>", "why": "<why it \
bears on the adjuster's question>"}}], "referral_reason": "<one or two neutral sentences>", \
"summary_for_adjuster": "<two or three neutral sentences>"}}

Rules:
1. Never write that a claim, loss or item is covered, payable, excluded, declined, approved, \
rejected or denied. Say a clause is "arguable on these facts" and that the adjuster should weigh \
it. Quote clause titles in double quotation marks.
2. Only cite a chunk_id that appeared in a search_wording result in THIS conversation. Do not \
state any clause, figure or endorsement you have not seen in a tool result.
3. Facts come from the claim narrative only. Do not include any person's name, address or injury \
details — describe what happened, not who it happened to.
4. If no exclusion is arguable, leave exclusion_candidates empty. An honest empty list is correct.
5. If search_wording returns nothing in force, say so in the referral and stop searching.
6. Output exactly one Thought/Action block or one Thought/Final Answer block per turn.
"""

_ACTION_NAME = re.compile(r"Action:\s*([A-Za-z_][A-Za-z0-9_]*)")
_HAS_FINAL = re.compile(r"Final Answer\s*:", re.IGNORECASE)
HIDDEN_PARAMS = {"trace_id"}
SEARCH_TOOLS = {"search_wording", "get_limits"}

# triage-v2 -> triage-v3: the prompt (step 3) and the search_wording tool description no longer quote exclusion wording. v2
# listed five clauses' own phrases, including the geographical one, as "the policy's own phrasing" to search with — handing the
# model the clause text for the cases it was being scored on (4 of 89 logged queries were those phrases verbatim, in CLM-2026-00509
# and -00514). See SEAMS.md S21 and tests/test_no_policy_wording_in_prompts.py. Results produced under v2 are NOT results for v3.
PROMPT_VERSION = "triage-v3"


def prompt_sha(tool_block: str = "") -> str:
    return hashlib.sha256(SYSTEM_PROMPT_TEMPLATE.encode("utf-8")).hexdigest()[:12]


@dataclass
class RunState:
    trace_id: str
    claim: claim_files.ClaimFile
    policy_number: str | None = None
    loss_date: str | None = None
    product: str | None = None
    in_force: bool | None = None
    in_force_result: dict | None = None
    limits: dict | None = None
    referral: dict | None = None
    retrieved: dict[str, dict] = field(default_factory=dict)       # chunk_id -> hit
    called: list[str] = field(default_factory=list)
    overrides: list[dict] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    spans: list[dict] = field(default_factory=list)
    arg_violations: list[dict] = field(default_factory=list)   # outcome statements in tool ARGS
    searches: int = 0
    exclusions_read: bool = False        # a retrieved chunk this run was the policy's "not covered" section
    index: str | None = None            # which chunking the wording server reported using


# ------------------------------------------------------------------------------ pure helpers

# The exclusion clause must actually have been READ before a claim is referred. The agent writes its own queries from the claim's
# vocabulary, and an exclusion rarely uses it ("a trip to Nepal" is not "outside the geographical area stated in the schedule"), so
# whether the exclusion list ever reached the model depended on query luck — nothing in the code required it. This does, and names no
# policy wording: it checks only that a retrieved chunk's section heading is the policy's "what is not covered" clause. The gate
# is in the host (like tool order), so the model cannot skip it. TRIAGE_EXCLUSIONS_GATE=off exists only for the before/after measurement.
EXCLUSION_CLAUSE = re.compile(r"not covered", re.IGNORECASE)
EXCLUSIONS_STEP = 'search_wording for the section titled "What is not covered" and read its whole list'


def exclusions_gate_enabled() -> bool:
    return os.environ.get("TRIAGE_EXCLUSIONS_GATE", "on").lower() != "off"


def hits_exclusion_clause(hits) -> bool:
    return any(EXCLUSION_CLAUSE.search(str(h.get("clause") or "")) for h in hits or [] if isinstance(h, dict))


def missing_steps(state: RunState) -> list[str]:
    """What must still happen before the claim may be referred / the answer accepted."""
    need = []
    if "lookup_policy" not in state.called:
        need.append("lookup_policy")
    elif "check_in_force" not in state.called:
        need.append("check_in_force")
    elif state.in_force:
        if state.searches == 0:
            need.append("search_wording")
        elif not state.exclusions_read and exclusions_gate_enabled():
            need.append(EXCLUSIONS_STEP)
        if "get_limits" not in state.called:
            need.append("get_limits")
    return need


def authoritative_args(state: RunState, tool: str, args: dict) -> tuple[dict, list[dict]]:
    """Overwrite every argument the claims system already knows. Returns (args, overrides)."""
    forced: dict = {}
    if tool in ("lookup_policy", "get_limits", "refer_to_adjuster"):
        forced["claim_number"] = state.claim.claim_number
    if state.policy_number and tool == "check_in_force":
        forced["policy_number"] = state.policy_number
    if state.loss_date and tool in ("check_in_force", "search_wording"):
        forced["loss_date"] = state.loss_date
    if state.product and tool == "search_wording":
        forced["product"] = state.product
    out, overrides = dict(args), []
    for key, value in forced.items():
        if out.get(key) != value:
            overrides.append({"tool": tool, "arg": key, "model_sent": out.get(key), "used": value})
        out[key] = value
    return out, overrides


def guard_tool_args(state: RunState, tool: str, args: dict) -> dict:
    """Model-written text in a tool CALL is output too. The referral reason is what the adjuster
    reads first and is stored verbatim in the referral queue, so it gets the same check as the
    Final Answer (SEAMS.md S9): an outcome statement is replaced and the attempt recorded."""
    if tool != "refer_to_adjuster":
        return args
    safe, violations = triage_guard.guard_fields(
        {"reason": args.get("reason") or "", "flags": [str(f) for f in args.get("flags") or []]})
    state.arg_violations.extend({"tool": tool, **v} for v in violations)
    flags = safe["flags"] + [f for f in unresolved_flags(state) if f not in safe["flags"]]
    return {**args, "reason": safe["reason"], "flags": flags}


def unresolved_flags(state: RunState) -> list[str]:
    """A number the tools could not resolve is surfaced by code, not left to the model's prose
    (SEAMS.md S11): refusing to guess the deductible tier is right, silence about it is not."""
    ded = (state.limits or {}).get("deductible") or {}
    if ded.get("applies") and ded.get("amount") is None and ded.get("needs"):
        return [f"unresolved:deductible (needs {ded['needs']})"]
    return []


def gate(state: RunState, tool: str) -> str | None:
    """A reason this call must not run now, or None. Returned to the model as the observation."""
    if tool == "lookup_policy":
        return None
    if "lookup_policy" not in state.called and tool != "lookup_policy":
        return "BLOCKED: call lookup_policy first — you do not yet have the policy or the loss date."
    if tool == "search_wording" and "check_in_force" not in state.called:
        return "BLOCKED: call check_in_force before searching wording."
    if state.in_force is False and tool in SEARCH_TOOLS:
        return ("BLOCKED: the policy was not in force on the loss date, so no wording may be "
                "applied to this loss. Go to refer_to_adjuster and quote the check_in_force reason.")
    if tool == "refer_to_adjuster":
        need = missing_steps(state)
        if need:
            return f"BLOCKED: before referring, you still need to call: {', '.join(need)}."
    return None


def build_packet(state: RunState, model_out: dict, violations: list[dict]) -> dict:
    """Assemble the packet. Versions, dates and numbers are copied from tool results — the
    model contributes only which chunks to cite and the neutral prose around them."""
    wording, superseded = [], []
    for role, key in (("exclusion_candidate", "exclusion_candidates"),
                      ("relevant", "wording_relevant")):
        for item in model_out.get(key) or []:
            hit = state.retrieved.get(item.get("chunk_id"))
            if hit is None:
                continue
            if hit.get("superseded_by"):
                superseded.append({"chunk_id": hit["chunk_id"], "clause": hit["clause"],
                                   "amended_by": hit["superseded_by"]})
                continue
            wording.append({
                "role": role, "chunk_id": hit["chunk_id"], "document_id": hit["document_id"],
                "version": hit["version"], "effective_date": hit["effective_date"],
                "clause": hit["clause"], "resolved_against": state.loss_date,
                "citation": (f"{hit['document_id']} v{hit['version']} "
                             f"(effective {hit['effective_date']}) — {hit['clause']} "
                             f"[resolved against loss date {state.loss_date}]"),
                "why": item.get("why", ""), "excerpt": hit["text"][:400],
            })
    return {
        "trace_id": state.trace_id,
        "claim_number": state.claim.claim_number,
        "policy_number": state.policy_number,
        "product": state.product,
        "loss_date": state.loss_date,
        "in_force": state.in_force_result,
        "facts": model_out.get("facts", []),
        "wording": wording,
        "numbers": state.limits,
        "referral": {**(state.referral or {}), "reason": model_out.get("referral_reason", "")},
        "summary_for_adjuster": model_out.get("summary_for_adjuster", ""),
        "decision": None,        # this system never states a coverage decision
        "guard_violations": violations,
        "superseded_dropped": superseded,
    }


def _parse_lap(raw: str) -> dict:
    if _HAS_FINAL.search(raw):
        answer, err = _find_json_object(raw, "Final Answer")
        if answer is None:
            return {"kind": "malformed", "error": f"Final Answer did not parse as JSON: {err}"}
        return {"kind": "final", "answer": answer}
    name = _ACTION_NAME.search(raw)
    if not name:
        return {"kind": "malformed", "error": "no 'Final Answer:' and no 'Action:' found"}
    args, err = _find_json_object(raw, "Action Input")
    if args is None:
        return {"kind": "malformed", "error": f"Action Input did not parse: {err}"}
    return {"kind": "action", "tool": name.group(1), "args": args}


def validate_final(state: RunState, answer: dict) -> str | None:
    """A reason to bounce the Final Answer back to the model, or None if it is acceptable."""
    for key in ("facts", "exclusion_candidates", "referral_reason", "summary_for_adjuster"):
        if key not in answer:
            return f"Final Answer is missing the field {key!r}."
    if state.referral is None:
        return "You have not called refer_to_adjuster yet. Call it, then give your Final Answer."
    need = missing_steps(state)
    if need:
        return f"You have not yet called: {', '.join(need)}."
    seen = set(state.retrieved)
    for key in ("exclusion_candidates", "wording_relevant"):
        for item in answer.get(key) or []:
            if not isinstance(item, dict) or item.get("chunk_id") not in seen:
                bad = item.get("chunk_id") if isinstance(item, dict) else item
                return (f"{key} cites chunk_id {bad!r}, which no search_wording result in this "
                        f"conversation returned. Valid ids: {sorted(seen) or 'none yet'}.")
    return None


def _schema_type(prop: dict) -> str:
    """Plain type name for the prompt. Dumping the raw schema fragment ({"title": ..., "type":
    "string"}) taught the model to send {"type": "room rent"} as an argument value: 16 rejected
    search calls in the first integrated run (SEAMS.md S10)."""
    kind = prop.get("type")
    if kind is None and prop.get("anyOf"):
        kind = " | ".join(str(o.get("type")) for o in prop["anyOf"])
    return str(kind or "string")


def _tool_block(tools: dict) -> str:
    lines = []
    for name, tool in tools.items():
        props = {k: v for k, v in (tool.input_schema.get("properties") or {}).items()
                 if k not in HIDDEN_PARAMS}
        required = set(tool.input_schema.get("required") or [])
        sig = ", ".join(f"{k}: {_schema_type(v)}{'' if k in required else ' (optional)'}"
                        for k, v in props.items())
        lines.append(f"- {name}({sig})\n  {' '.join(tool.description.split())}")
    return "\n".join(lines)


def _absolutise(servers: list[dict]) -> list[dict]:
    out = []
    for s in servers:
        s = dict(s)
        if s["command"].startswith("./"):
            s["command"] = str(ROOT / s["command"][2:])
        s["args"] = [str(ROOT / a) if a.startswith("src/") else a for a in s["args"]]
        out.append(s)
    return out


def _summarise_result(tool: str, result: dict | str) -> dict:
    """What the host trace keeps of a tool result: ids and numbers, not wording text (a log
    that stores wording through a PII redactor corrupts it) and never a claimant's words."""
    if not isinstance(result, dict):
        return {"text_chars": len(str(result))}
    if tool == "search_wording":
        return {"chunk_ids": [h["chunk_id"] for h in result.get("hits", [])],
                "dropped_not_in_force": result.get("dropped_not_in_force")}
    if tool == "get_limits":
        d = result.get("deductible") or {}
        return {"deductible": d.get("amount"), "deductible_doc": d.get("document_id"),
                "co_payment": (result.get("co_payment") or {}).get("percent"),
                "policy_limit": (result.get("policy_limit") or {}).get("amount")}
    if tool == "check_in_force":
        return {"in_force": result.get("in_force"), "reason": result.get("reason")}
    if tool == "lookup_policy":
        return {k: result.get(k) for k in ("policy_number", "product", "loss_date")}
    return {k: result.get(k) for k in ("referral_id", "queue")}


# ------------------------------------------------------------------------------ the loop

async def _dispatch(registry: MCPToolRegistry, state: RunState, tool: str, args: dict) -> str:
    """Gate, overwrite authoritative args, inject the trace id, call over MCP, update state."""
    blocked = gate(state, tool)
    if blocked:
        state.blocked.append({"tool": tool, "reason": blocked})
        state.spans.append({"source": "host", "kind": "tool", "tool": tool, "blocked": True,
                            "latency_ms": 0.0})
        return blocked
    if tool not in registry.tools:
        return f"ERROR: unknown tool {tool!r}. Available: {sorted(registry.tools)}"

    args = guard_tool_args(state, tool, args)
    args, overrides = authoritative_args(state, tool, args)
    state.overrides.extend(overrides)
    if "trace_id" in (registry.tools[tool].input_schema.get("properties") or {}):
        args["trace_id"] = state.trace_id

    started = time.perf_counter()
    try:
        text = await registry.dispatch(tool, args)
        ok, error = True, None
    except Exception as exc:                                          # noqa: BLE001 — shown to the model
        text, ok, error = f"ERROR: {exc}", False, str(exc)
    latency = round((time.perf_counter() - started) * 1000, 1)

    result: dict | str = text
    if ok:
        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            pass
    if ok and isinstance(result, dict):
        state.called.append(tool)
        if tool == "lookup_policy":
            state.policy_number = result.get("policy_number")
            state.loss_date = result.get("loss_date")
            state.product = result.get("product")
        elif tool == "check_in_force":
            state.in_force = bool(result.get("in_force"))
            state.in_force_result = result
        elif tool == "search_wording":
            state.searches += 1
            state.index = state.index or result.get("index")
            state.exclusions_read = state.exclusions_read or hits_exclusion_clause(result.get("hits"))
            for hit in result.get("hits", []):
                state.retrieved[hit["chunk_id"]] = hit
        elif tool == "get_limits":
            state.limits = result
        elif tool == "refer_to_adjuster":
            state.referral = result
    state.spans.append({"source": "host", "kind": "tool", "tool": tool,
                        "server": registry.tools[tool].server, "latency_ms": latency,
                        "ok": ok, "error": error, "overrides": overrides or None,
                        "result": _summarise_result(tool, result)})
    return text


async def run_with_registry(registry: MCPToolRegistry, claim_number: str,
                            budgets: Budgets = TRIAGE_BUDGETS, provider: str | None = None,
                            model: str | None = None, write_trace: bool = True,
                            submitted_by: str | None = None) -> dict:
    claim = claim_files.get(claim_number)
    state = RunState(trace_id=span_log.new_trace_id(), claim=claim)
    usage = UsageAccumulator()
    if provider:
        usage.provider = provider
    if model:
        usage.model = model

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(tool_block=_tool_block(registry.tools))
    # The claimant's words are scrubbed BEFORE the model sees them: it needs the facts, not the
    # names, and a model that never saw a name cannot repeat one into a log or a tool call.
    narrative = redact.scrub_claimant(claim.narrative)
    task = (f"Triage claim {claim.claim_number}.\n\nClaim narrative (identifying details "
            f"removed):\n{narrative}\n\nAdjuster's question: {redact.scrub_claimant(claim.coverage_question)}")

    started_all = time.perf_counter()
    stage = {"generation": 0.0, "tools": 0.0}
    transcript, steps = "", []
    final_out, stop_reason = None, None
    last_rejected, repeats, iteration = None, 0, 0

    while True:
        hit = exceeded(budgets, usage, iteration)
        if hit:
            stop_reason = f"budget_exceeded: {hit}"
            break
        iteration += 1
        user_turn = (f"TASK\n{task}\n\nTRANSCRIPT SO FAR\n{transcript or '(nothing yet)'}\n\n"
                     "What is your next Thought and Action, or your Final Answer?")
        before = usage.as_dict()
        t0 = time.perf_counter()
        try:
            raw = usage.call_llm(system_prompt, user_turn)
        except llm.LLMError as exc:
            steps.append({"lap": iteration, "kind": "provider_error", "error": str(exc)})
            state.spans.append({"source": "host", "kind": "llm", "lap": iteration, "ok": False,
                                "latency_ms": round((time.perf_counter() - t0) * 1000, 1)})
            transcript += f"[the model call for this lap failed: {exc}. Try again.]\n\n"
            continue
        after = usage.as_dict()
        lat = time.perf_counter() - t0
        stage["generation"] += lat
        state.spans.append({
            "source": "host", "kind": "llm", "lap": iteration, "ok": True,
            "latency_ms": round(lat * 1000, 1),
            "prompt_tokens": after["prompt_tokens"] - before["prompt_tokens"],
            "completion_tokens": after["completion_tokens"] - before["completion_tokens"],
            "cost_usd": round(after["cost_usd"] - before["cost_usd"], 6)})

        parsed = _parse_lap(raw)
        steps.append({"lap": iteration, "kind": parsed["kind"], "raw_output": raw,
                      "tool": parsed.get("tool")})

        if parsed["kind"] == "final":
            reason = validate_final(state, parsed["answer"])
            if reason is None:
                final_out = parsed["answer"]
                stop_reason = "final_answer"
                break
            if parsed["answer"] == last_rejected:
                repeats += 1
            else:
                last_rejected, repeats = parsed["answer"], 1
            if repeats >= 3:
                stop_reason = "repeated_rejection: the same Final Answer was rejected 3 times"
                break
            transcript += f"{raw.strip()}\nObservation: REJECTED — {reason}\n\n"
            continue

        if parsed["kind"] == "action":
            t1 = time.perf_counter()
            observation = await _dispatch(registry, state, parsed["tool"], parsed["args"])
            stage["tools"] += time.perf_counter() - t1
            transcript += f"{raw.strip()}\nObservation: {observation}\n\n"
            continue

        transcript += (f"{raw.strip()}\nObservation: ERROR — {parsed['error']}. Reply with exactly "
                       "one Thought/Action block or one Thought/Final Answer block.\n\n")

    # Invariant: every request ends in a referral. If the loop did not get there, the host does.
    if state.referral is None:
        reason_text = f"Triage did not complete ({stop_reason}); the file is passed on as it stands."
        await _dispatch_forced_referral(registry, state, reason_text)
    packet_out = final_out or {"facts": [], "exclusion_candidates": [], "referral_reason":
                               f"Triage did not complete: {stop_reason}.",
                               "summary_for_adjuster": "Triage did not complete; adjuster to review the file."}

    safe, violations = triage_guard.guard_fields({
        "facts": packet_out.get("facts", []),
        "referral_reason": packet_out.get("referral_reason", ""),
        "summary_for_adjuster": packet_out.get("summary_for_adjuster", ""),
        "exclusion_why": [i.get("why", "") for i in packet_out.get("exclusion_candidates") or []
                          if isinstance(i, dict)],
        "relevant_why": [i.get("why", "") for i in packet_out.get("wording_relevant") or []
                         if isinstance(i, dict)],
    })
    for key, src_key in (("exclusion_why", "exclusion_candidates"), ("relevant_why", "wording_relevant")):
        items = [i for i in packet_out.get(src_key) or [] if isinstance(i, dict)]
        for item, why in zip(items, safe[key]):
            item["why"] = why
    packet_out["facts"] = safe["facts"]
    packet_out["referral_reason"] = safe["referral_reason"]
    packet_out["summary_for_adjuster"] = safe["summary_for_adjuster"]
    packet = build_packet(state, packet_out, violations + state.arg_violations)

    usage_dict = usage.as_dict()
    wall = round(time.perf_counter() - started_all, 3)
    result = {
        "trace_id": state.trace_id, "system": "triage", "claim_number": claim.claim_number,
        "submitted_by": submitted_by, "prompt_version": PROMPT_VERSION, "prompt_sha": prompt_sha(),
        "tools_discovered": sorted(registry.tools), "index": state.index,
        "packet": packet, "stop_reason": stop_reason, "iterations": iteration,
        "guard_violations": violations + state.arg_violations,
        "overrides": state.overrides, "blocked": state.blocked,
        "usage": usage_dict, "wall_seconds": wall,
        "stage_seconds": {k: round(v, 3) for k, v in stage.items()},
        "retrieved_context": {cid: hashlib.sha256(h["text"].encode()).hexdigest()[:12]
                              for cid, h in state.retrieved.items()},
        "spans": state.spans, "steps": steps,
    }
    if write_trace:
        span_log.append({k: v for k, v in result.items() if k != "packet"} | {
            "packet": {**packet, "wording": [{k: v for k, v in w.items() if k != "excerpt"}
                                             for w in packet["wording"]]},
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "source": "host"}, span_log.TRACES_FILE)
    return result


async def _dispatch_forced_referral(registry: MCPToolRegistry, state: RunState, reason: str) -> None:
    """The host makes the referral itself — bypassing the gate on purpose, because the point of
    this call is that a run which fell over still ends with a human holding the file."""
    args = {"claim_number": state.claim.claim_number, "reason": reason,
            "flags": ["triage_incomplete"], "trace_id": state.trace_id}
    started = time.perf_counter()
    try:
        text = await registry.dispatch("refer_to_adjuster", args)
        state.referral = json.loads(text)
        ok, err = True, None
    except Exception as exc:                                          # noqa: BLE001
        ok, err = False, str(exc)
    state.spans.append({"source": "host", "kind": "tool", "tool": "refer_to_adjuster",
                        "server": registry.tools["refer_to_adjuster"].server, "forced": True,
                        "ok": ok, "error": err,
                        "latency_ms": round((time.perf_counter() - started) * 1000, 1)})


async def warm_up(registry: MCPToolRegistry) -> float:
    """Make the wording server load its embedder and reranker BEFORE any request's clock starts.

    The first search in a fresh server process pays the model-load cost (minutes on a loaded
    machine; measured live — the first end-to-end run spent its whole 240s wall budget on it).
    Folding that into claim 1's latency would blame the claim for the server's start-up, the
    same reason Week 7's race warmed retrieval up and reported it separately. Tagged
    ``warmup`` so it never joins a real request's trace.
    """
    if "search_wording" not in registry.tools:
        return 0.0
    started = time.perf_counter()
    try:
        await registry.dispatch("search_wording", {"query": "warm up", "product": "motor",
                                                   "loss_date": "2026-01-01", "top_k": 1,
                                                   "trace_id": "warmup"})
    except Exception:                                                  # noqa: BLE001 — best effort
        pass
    return time.perf_counter() - started


async def run_many(claim_numbers: list[str], config_path: str | Path = DEFAULT_CONFIG,
                   on_result=None, **kwargs) -> list[dict]:
    """Triage several claims against ONE pair of MCP server processes — starting them per claim
    would reload the embedder and reranker every time."""
    servers = _absolutise(load_config(config_path))
    out = []
    async with MCPToolRegistry(servers) as registry:
        warm_seconds = await warm_up(registry)
        for number in claim_numbers:
            result = await run_with_registry(registry, number, **kwargs)
            result["server_warmup_seconds"] = round(warm_seconds, 1)
            out.append(result)
            if on_result:
                on_result(result)
    return out


def triage(claim_number: str, **kwargs) -> dict:
    """Synchronous convenience wrapper — what ``cli.py triage`` calls."""
    return asyncio.run(run_many([claim_number], **kwargs))[0]
