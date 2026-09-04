"""The hand-built agent loop. This is the whole thing — no framework underneath it.

    Thought -> Action -> Observation -> Thought -> ... -> Final Answer

One call to ``llm.chat_with_usage`` per lap. The system prompt (tool descriptions, output
format, rules) is fixed; the *user* turn is the growing transcript re-sent in full each lap,
because the underlying ``chat()`` primitive this whole project shares is single-turn
(system, user) -> text, not a persistent multi-turn session. That single design fact is why
token accounting has to sum across laps rather than read the last call (see ``usage.py``) —
lap 4 pays for the text of laps 1 through 3 all over again, every time.

Every lap is logged — the raw model output, the parsed action, the tool's observation, and
the cumulative usage after that lap — into ``result["steps"]``, which is what makes "every
step visible" checkable rather than asserted.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict

from . import claims_store, tools, trace
from .budgets import Budgets, exceeded
from .usage import UsageAccumulator
from .. import llm

SYSTEM_PROMPT_TEMPLATE = """\
You are a motor own-damage claims triage agent. You decide whether a claim is PAYABLE, \
NOT_PAYABLE, or REFERRED, and if PAYABLE, the exact amount owed to the claimant.

You have exactly three tools:

{tool_block}

On every turn, output ONE of the following two things, and nothing else:

Thought: <your reasoning about what to do next>
Action: <one tool name, exactly as listed above>
Action Input: <a single JSON object with that tool's parameters>

Thought: <your reasoning for why you are now done>
Final Answer: {{"status": "PAYABLE|NOT_PAYABLE|REFERRED", "payable_amount": <number or null>, \
"exclusion_clause": "<document_id and clause/section, or null>", "rationale": "<one or two \
sentences>"}}

Rules:
1. Call get_claim first, always, before anything else.
2. Before you reach ANY final decision — PAYABLE, NOT_PAYABLE, or REFERRED — call \
search_policy AT LEAST ONCE to check the exclusion list ("what is not covered") against \
this claim's specific facts, even when nothing in the notes looks risky. The only way to \
know nothing excludes a claim is to check, not to notice that nothing obviously suspicious \
was mentioned — and REFERRED without ever checking is a guess wearing a caution label, not \
an honest one. If something in the notes suggests a specific exclusion — no valid licence, \
alcohol or drugs, unlicensed or unauthorised use such as hire or reward, mechanical or \
electrical breakdown with no external cause, damage limited to tyres alone, or a genuinely \
ambiguous cause — name that fact directly in your search query; otherwise search generally \
for what is not covered.
3. A clause of the form "X is excluded UNLESS Y" only avoids the exclusion when Y is true \
of THESE facts. Check Y against the claim before applying any exception inside an \
exclusion — never grant a partial or reduced payout under an exception whose own condition \
the facts do not satisfy.
4. The compulsory deductible can change between the base wording and a later endorsement. \
Call search_policy to confirm which deductible amount is actually in force for this claim's \
date of loss — do not assume the base wording still applies, and never state a deductible \
figure you have not actually retrieved.
5. If part of the claimed amount is for something the policy does not cover (for example \
hire-car or replacement-vehicle charges while a covered repair is also being claimed), \
exclude only that part before computing the payout — the rest can still be payable.
6. Once you have retrieved the exclusion list and the damage described does not match \
anything in it, that IS the answer: it is not excluded, so proceed to PAYABLE. Do not \
output REFERRED merely because you have not seen a passage that explicitly says this exact \
kind of damage is covered — a motor policy states what is excluded, not an exhaustive list \
of what is included, so the absence of a matching exclusion is a conclusion, not an open \
question.
7. Reserve REFERRED for when the passages you retrieved actively conflict about this claim \
(for example, one clause covers the peril and a different clause could equally exclude the \
same event), or a fact you would need is simply missing from the claim file — not for an \
ordinary claim whose exclusion check came back clean.
8. Always call compute_payout to get the payable amount once status, the claim amount to \
pay against, and the deductible are all known. Never compute the subtraction yourself — copy \
compute_payout's returned number into your Final Answer. A Final Answer whose payable_amount \
does not match compute_payout's own returned value will be rejected.
9. Output exactly one Thought/Action block or one Thought/Final Answer block per turn. No \
text before "Thought:" and nothing after the JSON.
"""


def _tool_block() -> str:
    lines = []
    for name, (spec, _fn) in tools.TOOLS.items():
        params = ", ".join(f"{k} ({v})" for k, v in spec["parameters"].items())
        lines.append(f"- {name}({params})\n  {spec['description']}")
    return "\n".join(lines)


SYSTEM_PROMPT = SYSTEM_PROMPT_TEMPLATE.format(tool_block=_tool_block())


def _find_json_object(text: str, after: str) -> tuple[dict | None, str]:
    """Find ``after`` in text, then bracket-match the first ``{...}`` following it.

    A regex for nested JSON is a losing game the moment a rationale string contains a brace
    or a colon; matching brackets by hand is a dozen lines and never misparses on structure
    it hasn't seen before.
    """
    idx = text.find(after)
    if idx == -1:
        return None, ""
    start = text.find("{", idx)
    if start == -1:
        return None, ""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                blob = text[start : i + 1]
                try:
                    return json.loads(blob), blob
                except json.JSONDecodeError as exc:
                    return None, f"JSON did not parse: {exc}"
    return None, "no matching closing brace found"


_ACTION_NAME = re.compile(r"Action:\s*([A-Za-z_][A-Za-z0-9_]*)")
_HAS_FINAL = re.compile(r"Final Answer\s*:", re.IGNORECASE)

REQUIRED_FINAL_FIELDS = ("status", "payable_amount", "exclusion_clause", "rationale")
VALID_STATUSES = {"PAYABLE", "NOT_PAYABLE", "REFERRED"}


def _parse_lap(raw: str) -> dict:
    """Classify one model turn as a tool call, a final answer, or malformed.

    Returns ``{"kind": "action", "tool": ..., "args": ...}``,
    ``{"kind": "final", "answer": {...}}``, or ``{"kind": "malformed", "error": ...}``.
    """
    if _HAS_FINAL.search(raw):
        answer, err = _find_json_object(raw, "Final Answer")
        if answer is None:
            return {"kind": "malformed", "error": f"Final Answer block did not parse: {err}"}
        missing = [f for f in REQUIRED_FINAL_FIELDS if f not in answer]
        if missing:
            return {"kind": "malformed", "error": f"Final Answer missing fields: {missing}"}
        if answer["status"] not in VALID_STATUSES:
            return {"kind": "malformed",
                    "error": f"status must be one of {sorted(VALID_STATUSES)}, "
                             f"got {answer['status']!r}"}
        return {"kind": "final", "answer": answer}

    name_match = _ACTION_NAME.search(raw)
    if not name_match:
        return {"kind": "malformed",
                "error": "no 'Final Answer:' and no 'Action:' found in the model's turn"}
    args, err = _find_json_object(raw, "Action Input")
    if args is None:
        return {"kind": "malformed", "error": f"Action Input did not parse: {err}"}
    return {"kind": "action", "tool": name_match.group(1), "args": args}


def run(
    claim_id: str,
    budgets: Budgets = Budgets(),
    provider: str | None = None,
    model: str | None = None,
    write_trace: bool = True,
) -> dict:
    """Triage one claim. Returns a result dict with the decision, usage, and every step."""
    usage = UsageAccumulator()
    if provider:
        usage.provider = provider
    if model:
        usage.model = model

    task = (
        f"Triage claim {claim_id}. Decide PAYABLE, NOT_PAYABLE, or REFERRED, and if "
        f"PAYABLE, the exact amount owed. Begin."
    )
    transcript = ""
    steps: list[dict] = []
    last_payout_observation: float | None = None
    stop_reason = None
    final_answer = None
    iteration = 0

    while True:
        budget_hit = exceeded(budgets, usage, iteration)
        if budget_hit:
            stop_reason = f"budget_exceeded: {budget_hit}"
            break

        iteration += 1
        user_turn = (
            f"TASK\n{task}\n\n"
            f"TRANSCRIPT SO FAR\n{transcript or '(nothing yet)'}\n\n"
            "What is your next Thought and Action, or your Final Answer?"
        )
        try:
            raw = usage.call_llm(SYSTEM_PROMPT, user_turn)
        except llm.LLMError as exc:
            # One lap's provider failure must not take down the claim, and must not take
            # down the whole 10-claim batch it is part of. The failed call still counts
            # toward the iteration budget — a provider that fails every time still gets
            # stopped by max_iterations rather than retried without limit — but this claim
            # gets another lap to try again rather than crashing the entire race.
            steps.append({"lap": iteration, "raw_output": None,
                         "parsed": {"kind": "provider_error", "error": str(exc)},
                         "cumulative_usage": usage.as_dict()})
            transcript += (
                f"[the model call for this lap failed: {exc}. Try again.]\n\n"
            )
            continue
        parsed = _parse_lap(raw)

        step = {
            "lap": iteration,
            "raw_output": raw,
            "parsed": parsed,
            "cumulative_usage": usage.as_dict(),
        }

        if parsed["kind"] == "final":
            answer = parsed["answer"]
            # A verification gate, in the same spirit as generator.py's citation check: the
            # model was told to copy compute_payout's number, not invent one. This is not
            # decorative — a Final Answer that fails it is REJECTED, the same way an
            # ungrounded citation gets downgraded rather than shown. Logging the mismatch
            # without acting on it would make this check theatre: it was built after
            # watching the agent skip compute_payout entirely on claim C-001, invent a
            # deductible from a non-existent endorsement id, and state a confidently wrong
            # number — exactly the failure a verification gate exists to stop, not narrate.
            claimed_amount = answer.get("payable_amount")
            verified = (
                claimed_amount is None and last_payout_observation is None
            ) or (
                claimed_amount is not None and last_payout_observation is not None
                and abs(float(claimed_amount) - float(last_payout_observation)) < 0.01
            )
            step["payout_verified"] = verified
            steps.append(step)

            if verified:
                final_answer = answer
                stop_reason = "final_answer"
                break

            transcript += (
                f"{raw.strip()}\nObservation: REJECTED — payable_amount "
                f"{claimed_amount!r} does not match compute_payout's last returned value "
                f"({last_payout_observation!r}). Call compute_payout and copy its exact "
                "returned number into payable_amount before answering again.\n\n"
            )
            continue

        if parsed["kind"] == "action":
            tool_name, args = parsed["tool"], parsed["args"]
            try:
                observation = tools.dispatch(tool_name, args)
                if tool_name == "compute_payout":
                    last_payout_observation = observation
                obs_text = json.dumps(observation, default=str)
            except Exception as exc:                       # noqa: BLE001 — surfaced as text
                obs_text = f"ERROR: {exc}"
            step["tool"] = tool_name
            step["tool_args"] = args
            step["observation"] = obs_text
            steps.append(step)
            transcript += (
                f"{raw.strip()}\nObservation: {obs_text}\n\n"
            )
            continue

        # malformed — tell the model exactly what was wrong with its own last turn and let
        # it try again. This still consumes a lap, which is exactly why max_iterations
        # exists: a model that cannot self-correct its format burns its budget and stops,
        # rather than looping forever.
        steps.append(step)
        transcript += (
            f"{raw.strip()}\nObservation: ERROR — {parsed['error']}. Reply with exactly "
            "one Thought/Action/Action Input block or one Thought/Final Answer block.\n\n"
        )

    if final_answer is None:
        # A budget fired before the model produced a Final Answer. Referring the claim is
        # the safe default here — the same abstain-rather-than-guess principle the citation
        # and grounding gates use everywhere else in this project.
        final_answer = {
            "status": "REFERRED", "payable_amount": None, "exclusion_clause": None,
            "rationale": f"Stopped by a budget before reaching a decision: {stop_reason}.",
        }

    result = {
        "system": "agent",
        "claim_id": claim_id,
        "status": final_answer["status"],
        "payable_amount": final_answer.get("payable_amount"),
        "exclusion_clause": final_answer.get("exclusion_clause"),
        "rationale": final_answer.get("rationale"),
        "stop_reason": stop_reason,
        "iterations": iteration,
        "usage": usage.as_dict(),
        "steps": steps,
    }
    if write_trace:
        trace.record(result)
    return result
