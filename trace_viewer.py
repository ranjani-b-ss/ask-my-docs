#!/usr/bin/env python
"""Trace viewer — Week 7's agent-vs-workflow race and Week 8's trajectory eval, both read
straight from what already ran, instead of a spreadsheet.

    ./.venv/bin/python -m streamlit run trace_viewer.py --server.port 8502

Read-only: it only reads what eval/race.py, eval/trajectory_eval.py and src/agent/*.py already
wrote to disk — traces/agent_traces.jsonl for the step-by-step reasoning (Week 7's race AND
Week 8's after-mitigation run share this one file), traces/pre_mitigation_agent_traces.jsonl
for Week 8's before snapshot, eval/race.csv for the scoreboard, eval/race_cases.yaml for the
gold answer and its rationale. No LLM calls happen here, and nothing on disk is changed by
opening this page.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from eval.trajectory_eval import mode_counts, score_trace, summarise  # noqa: E402

TRACE_FILE = ROOT / "traces" / "agent_traces.jsonl"
BEFORE_TRACE_FILE = ROOT / "traces" / "pre_mitigation_agent_traces.jsonl"
RACE_CSV = ROOT / "eval" / "race.csv"
RACE_CASES = ROOT / "eval" / "race_cases.yaml"

st.set_page_config(page_title="Claims Agent Trace Viewer", page_icon="🏁", layout="wide")


@st.cache_data
def load_traces() -> dict[str, dict[str, dict]]:
    """claim_id -> {"agent": row, "workflow": row}. Keeps the LAST row per (system, claim)
    so re-running the race and appending more lines doesn't show a stale run."""
    by_claim: dict[str, dict[str, dict]] = {}
    if not TRACE_FILE.exists():
        return by_claim
    for line in TRACE_FILE.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        by_claim.setdefault(row["claim_id"], {})[row["system"]] = row
    return by_claim


@st.cache_data
def load_scoreboard() -> list[dict]:
    if not RACE_CSV.exists():
        return []
    with RACE_CSV.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


@st.cache_data
def load_gold() -> dict[str, dict]:
    if not RACE_CASES.exists():
        return {}
    cases = yaml.safe_load(RACE_CASES.read_text(encoding="utf-8"))["cases"]
    return {c["claim_id"]: c for c in cases}


def status_badge(status: str) -> None:
    if status == "PAYABLE":
        st.success(f"**{status}**")
    elif status == "NOT_PAYABLE":
        st.error(f"**{status}**")
    else:
        st.warning(f"**{status}**")


def usage_row(usage: dict) -> None:
    cols = st.columns(2)
    cols[0].metric("LLM calls", usage.get("llm_calls", 0))
    cols[1].metric("Tokens", f"{usage.get('total_tokens', 0):,}")
    cols = st.columns(2)
    cols[0].metric("Cost", f"${usage.get('cost_usd', 0):.5f}")
    cols[1].metric("Wall time", f"{usage.get('wall_seconds', 0):.1f}s")


def claim_facts(agent_row: dict | None, workflow_row: dict | None) -> dict | None:
    if workflow_row:
        s1 = next((s for s in workflow_row["steps"] if s.get("action") == "get_claim"), None)
        if s1:
            return s1["result"]
    if agent_row:
        s1 = next((s for s in agent_row["steps"] if s.get("tool") == "get_claim"), None)
        if s1:
            try:
                return json.loads(s1["observation"])
            except (json.JSONDecodeError, TypeError):
                pass
    return None


def render_agent_column(row: dict | None, gold_row: dict | None) -> None:
    if row is None:
        st.info("No agent trace recorded for this claim.")
        return

    status_badge(row["status"])
    passed = gold_row is not None and row["status"] == gold_row["status"] and (
        gold_row["status"] != "PAYABLE"
        or abs((row.get("payable_amount") or -1) - gold_row["payable_amount"]) <= 1
    )
    if gold_row:
        st.caption("✅ matches gold" if passed else "❌ does not match gold")
    st.write(
        f"payable_amount: **{row.get('payable_amount')}**  ·  "
        f"exclusion_clause: **{row.get('exclusion_clause') or '—'}**"
    )
    st.caption(row.get("rationale") or "")
    st.divider()
    usage_row(row["usage"])
    st.caption(f"stop_reason: `{row.get('stop_reason')}`  ·  iterations: {row.get('iterations')}")

    st.markdown("**Reasoning trace — Thought → Action → Observation**")
    for step in row["steps"]:
        parsed = step.get("parsed", {})
        kind = parsed.get("kind", "?")
        with st.expander(f"Lap {step['lap']} — {kind}", expanded=False):
            if kind == "action":
                st.code(step.get("raw_output", ""), language="text")
                st.markdown(f"**Observation** (`{step.get('tool')}`):")
                st.code(str(step.get("observation", ""))[:1500], language="json")
            elif kind == "final":
                st.code(step.get("raw_output", ""), language="text")
                verified = step.get("payout_verified")
                if verified is False:
                    st.error("payout REJECTED — did not match compute_payout's own number, "
                             "model was asked to try again")
                elif verified is True:
                    st.caption("payout verified against compute_payout's return value")
            elif kind == "provider_error":
                st.error(f"LLM call failed: {parsed.get('error')}")
            else:
                st.code(step.get("raw_output", "") or "", language="text")
                st.warning(f"malformed turn: {parsed.get('error')}")


def render_workflow_column(row: dict | None, gold_row: dict | None) -> None:
    if row is None:
        st.info("No workflow trace recorded for this claim.")
        return

    status_badge(row["status"])
    passed = gold_row is not None and row["status"] == gold_row["status"] and (
        gold_row["status"] != "PAYABLE"
        or abs((row.get("payable_amount") or -1) - gold_row["payable_amount"]) <= 1
    )
    if gold_row:
        st.caption("✅ matches gold" if passed else "❌ does not match gold")
    st.write(
        f"payable_amount: **{row.get('payable_amount')}**  ·  "
        f"deductible_applied: **{row.get('deductible_applied')}**  ·  "
        f"exclusion_clause: **{row.get('exclusion_clause') or '—'}**"
    )
    st.caption(row.get("rationale") or "")
    st.divider()
    usage_row(row["usage"])

    st.markdown("**Fixed sequence — always these 5 steps, in this order**")
    for step in row["steps"]:
        label = f"Step {step['step']} — {step['action']}"
        with st.expander(label, expanded=False):
            if step["step"] == 4 and "votes" in step:
                st.write(f"Votes: {step['votes']}  →  majority: **{step['parsed']['status']}**")
                for i, raw in enumerate(step.get("raw_outputs", []), start=1):
                    st.markdown(f"vote {i}:")
                    st.code(raw or "(call failed)", language="text")
            elif "args" in step:
                st.write("args:", step["args"])
                st.code(json.dumps(step.get("result", step.get("parsed")), indent=1,
                                   default=str)[:1500], language="json")
            else:
                st.code(json.dumps(step.get("parsed", step.get("result")), indent=1,
                                   default=str)[:1500], language="json")


def render_week7_tab() -> None:
    traces = load_traces()
    scoreboard = load_scoreboard()
    gold = load_gold()

    st.caption(
        "Read-only viewer over files `eval/race.py` and `src/agent/*.py` already wrote to "
        "disk. No LLM calls happen on this page."
    )

    if not traces:
        st.error(f"No traces found at `{TRACE_FILE.relative_to(ROOT)}`. Run "
                 "`./.venv/bin/python eval/race.py` first, then reload this page.")
        st.stop()

    st.subheader("Scoreboard — all claims, both systems")
    if scoreboard:
        view = [
            {
                "system": r["system"],
                "claim": r["claim_id"],
                "status": r["status"],
                "expected": r["expected_status"],
                "pass": "✅" if r["pass"] == "True" else "❌",
                "payable_amount": r["payable_amount"] or "—",
                "llm_calls": r["llm_calls"],
                "tokens": r["total_tokens"],
                "cost_usd": f"${float(r['cost_usd']):.5f}",
                "wall_s": f"{float(r['wall_seconds']):.1f}",
            }
            for r in scoreboard
        ]
        st.dataframe(view, use_container_width=True, hide_index=True)
    else:
        st.info("No `eval/race.csv` found — showing traces only, no scoreboard.")

    st.divider()

    claim_ids = sorted(traces)
    claim_id = st.selectbox("Pick a claim to inspect", claim_ids, key="week7_claim")
    row = traces[claim_id]
    gold_row = gold.get(claim_id)

    facts = claim_facts(row.get("agent"), row.get("workflow"))
    if facts:
        st.markdown(
            f"**{claim_id}** · date of loss `{facts.get('date_of_loss')}` · "
            f"{facts.get('vehicle_cc')}cc · claimed ₹{facts.get('claim_amount')}"
        )
        st.caption(facts.get("notes", ""))
    if gold_row:
        gold_line = f"**Gold answer:** `{gold_row['status']}`"
        if gold_row["status"] == "PAYABLE":
            gold_line += f", payable = ₹{gold_row['payable_amount']}"
        st.markdown(gold_line)
        with st.expander("Why (human-checked against the policy wording, never shown to "
                         "either system)"):
            st.write(gold_row["why"].strip())

    col_agent, col_workflow = st.columns(2)
    with col_agent:
        st.markdown("### 🤖 Agent — ReAct loop")
        render_agent_column(row.get("agent"), gold_row)
    with col_workflow:
        st.markdown("### ⚙️ Workflow — fixed sequence")
        render_workflow_column(row.get("workflow"), gold_row)


# ---------------------------------------------------------------------------------- Week 8


@st.cache_data
def load_agent_rows_at(path_str: str) -> dict[str, dict]:
    """claim_id -> its LAST recorded agent row in the given trace file."""
    path = Path(path_str)
    rows: dict[str, dict] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row["system"] == "agent":
            rows[row["claim_id"]] = row
    return rows


MODE_LABELS = {
    "skipped_mandatory_tool": "skipped mandatory tool (\"giving up quietly\")",
    "fabricated_argument": "fabricated argument (\"made-up inputs\")",
    "redundant_search_loop": "redundant search loop (\"loops\")",
    "wrong_tool_choice": "wrong tool choice",
    "hallucinated_tool_call": "hallucinated a fake tool call",
}

FLAGSHIP_NOTE = {
    "C-003": "🎯 the named right-answer-wrong-path case (§3 of WEEK8.md): outcome PASS, "
            "sequence FAIL — skipped search_policy entirely and cited a document that "
            "doesn't exist in the corpus.",
    "C-007": "⚠️ regression: correct and cheap before mitigation; after, the model "
            "hallucinated a fake tool call trying to game the gate, burned its whole "
            "iteration budget, and ended REFERRED — wrong (§6.1 of WEEK8.md).",
    "C-010": "⚠️ regression: correctly REFERRED before mitigation (Week 7 measured this "
            "exact fact pattern's own LLM accuracy at 33%); after, forced tool completion "
            "pressured a confident-but-wrong PAYABLE instead (§6.2 of WEEK8.md).",
}


def render_week8_tab() -> None:
    st.caption(
        "Read-only viewer over `eval/trajectory_eval.py`'s scoring of the same two trace "
        "files it's run against from the command line — the before snapshot and the current "
        "(after-mitigation) trace. No LLM calls happen on this page."
    )

    if not BEFORE_TRACE_FILE.exists() or not TRACE_FILE.exists():
        st.error("Need both `traces/pre_mitigation_agent_traces.jsonl` and "
                 "`traces/agent_traces.jsonl` to compare before/after. Run "
                 "`eval/trajectory_eval.py` first.")
        st.stop()

    before_claims = score_trace(BEFORE_TRACE_FILE)
    after_claims = score_trace(TRACE_FILE)
    before_summary = summarise(before_claims)
    after_summary = summarise(after_claims)
    before_modes = mode_counts(before_claims)
    after_modes = mode_counts(after_claims)

    st.subheader("The four numbers, before → after")
    metric_rows = [
        {"metric": "tool-choice accuracy", "before": f"{before_summary['tool_choice_accuracy']:.0%}",
         "after": f"{after_summary['tool_choice_accuracy']:.0%}"},
        {"metric": "argument validity rate", "before": f"{before_summary['argument_validity_rate']:.0%}",
         "after": f"{after_summary['argument_validity_rate']:.0%}"},
        {"metric": "step efficiency (mean)", "before": f"{before_summary['step_efficiency_mean']:.2f}×",
         "after": f"{after_summary['step_efficiency_mean']:.2f}×"},
        {"metric": "cost per claim, p50", "before": f"${before_summary['cost_p50']:.5f}",
         "after": f"${after_summary['cost_p50']:.5f}"},
        {"metric": "cost per claim, p99", "before": f"${before_summary['cost_p99']:.5f}",
         "after": f"${after_summary['cost_p99']:.5f}"},
        {"metric": "cost per claim, max", "before": f"${before_summary['cost_max']:.5f}",
         "after": f"${after_summary['cost_max']:.5f}"},
        {"metric": "outcome pass rate", "before": f"{before_summary['outcome_pass_rate']:.0%}",
         "after": f"{after_summary['outcome_pass_rate']:.0%}"},
        {"metric": "trajectory pass rate", "before": f"{before_summary['trajectory_pass_rate']:.0%}",
         "after": f"{after_summary['trajectory_pass_rate']:.0%}"},
    ]
    st.dataframe(metric_rows, use_container_width=True, hide_index=True)

    gap_before = before_summary["outcome_pass_rate"] - before_summary["trajectory_pass_rate"]
    gap_after = after_summary["outcome_pass_rate"] - after_summary["trajectory_pass_rate"]
    cols = st.columns(2)
    cols[0].metric("GAP before (outcome − trajectory)", f"{gap_before:+.0%}")
    cols[1].metric("GAP after", f"{gap_after:+.0%}", delta=f"{(gap_after - gap_before):+.0%}",
                   delta_color="inverse")

    st.divider()
    st.subheader("Regression — every failure mode, before vs after")
    reg_rows = []
    for mode in sorted(set(before_modes) | set(after_modes)):
        b, a = before_modes.get(mode, 0), after_modes.get(mode, 0)
        flag = "⬆️ WORSE" if a > b else ("⬇️ improved" if a < b else "— unchanged")
        reg_rows.append({"mode": MODE_LABELS.get(mode, mode), "before": b, "after": a,
                         "change": f"{a - b:+d}", "flag": flag})
    st.dataframe(reg_rows, use_container_width=True, hide_index=True)
    st.caption("`skipped_mandatory_tool` was the mitigation's target (§4–5 of WEEK8.md). "
              "Everything else on this table is a side effect, not the goal — see §6–7 of "
              "WEEK8.md for what each one means.")

    st.divider()
    st.subheader("Per-claim: outcome vs trajectory, before and after")
    per_claim_rows = []
    for cid in sorted(before_claims):
        b, a = before_claims[cid], after_claims.get(cid, {})
        per_claim_rows.append({
            "claim": cid,
            "before: outcome": "✅" if b.get("outcome_pass") else "❌",
            "before: sequence": "✅" if b.get("sequence_ok") else "❌",
            "before: args": "✅" if b.get("argument_ok") else "❌",
            "after: outcome": "✅" if a.get("outcome_pass") else "❌",
            "after: sequence": "✅" if a.get("sequence_ok") else "❌",
            "after: args": "✅" if a.get("argument_ok") else "❌",
        })
    st.dataframe(per_claim_rows, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Inspect one claim's before/after trace")
    before_rows = load_agent_rows_at(str(BEFORE_TRACE_FILE))
    after_rows = load_agent_rows_at(str(TRACE_FILE))
    gold = load_gold()
    claim_id = st.selectbox("Pick a claim", sorted(before_claims), key="week8_claim")

    if claim_id in FLAGSHIP_NOTE:
        st.info(FLAGSHIP_NOTE[claim_id])

    gold_row = gold.get(claim_id)
    col_before, col_after = st.columns(2)
    with col_before:
        st.markdown("### Before mitigation")
        render_agent_column(before_rows.get(claim_id), gold_row)
    with col_after:
        st.markdown("### After mitigation")
        render_agent_column(after_rows.get(claim_id), gold_row)


# ---------------------------------------------------------------------------------- Week 9

MCP_DIR = ROOT / "traces" / "mcp"


@st.cache_data
def load_json(path_str: str) -> dict | None:
    path = Path(path_str)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def render_mcp_steps(steps: list[dict]) -> None:
    for step in steps:
        parsed = step.get("parsed", {})
        kind = parsed.get("kind", "?")
        with st.expander(f"Lap {step['lap']} — {kind}", expanded=False):
            st.code(step.get("raw_output", ""), language="text")
            if step.get("tool"):
                st.markdown(f"**Observation** (`{step['tool']}`):")
                st.code(str(step.get("observation", ""))[:1500], language="json")
            elif kind == "final":
                st.caption(f"Final Answer: {parsed.get('answer', '')}")


def render_week9_tab() -> None:
    st.caption(
        "Read-only viewer over the real MCP artifacts this week produced — "
        "`agent_diff.txt`, `config_diff.txt`, `wire.json`, `risk_note.md`, and the captured "
        "query/error transcripts under `traces/mcp/`. No LLM calls and no MCP server "
        "processes are started by opening this page."
    )

    st.subheader("Tool discovery — before vs after adding server two")
    discovery = load_json(str(MCP_DIR / "discovery.json"))
    if discovery:
        cols = st.columns(2)
        with cols[0]:
            st.metric("Tools before", len(discovery["before"]))
            for t in discovery["before"]:
                st.write(f"- `{t['name']}` ({t['server']})")
        with cols[1]:
            st.metric("Tools after", len(discovery["after"]))
            for t in discovery["after"]:
                st.write(f"- `{t['name']}` ({t['server']})")
    else:
        st.info("No `traces/mcp/discovery.json` found.")

    st.divider()
    st.subheader("Requirement 2 — the agent module didn't change")
    diff_file = ROOT / "agent_diff.txt"
    config_diff_file = ROOT / "config_diff.txt"
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**`agent_diff.txt`**")
        if diff_file.exists():
            st.code(diff_file.read_text(encoding="utf-8"), language="text")
    with col_b:
        st.markdown("**`config_diff.txt`**")
        if config_diff_file.exists():
            st.code(config_diff_file.read_text(encoding="utf-8"), language="diff")

    st.divider()
    st.subheader("Requirement 1 — one real query against each server")
    q1 = load_json(str(MCP_DIR / "query_server_one.json"))
    q2 = load_json(str(MCP_DIR / "query_server_two.json"))
    col_q1, col_q2 = st.columns(2)
    with col_q1:
        st.markdown("### server one — policy-search")
        if q1:
            st.write(f"**Q:** {q1['question']}")
            st.success(q1["final_answer"])
            st.caption(f"{q1['iterations']} laps · ${q1['usage']['cost_usd']:.6f} · "
                      f"{q1['usage']['wall_seconds']:.1f}s")
            render_mcp_steps(q1["steps"])
    with col_q2:
        st.markdown("### server two — claims-system")
        if q2:
            st.write(f"**Q:** {q2['question']}")
            st.success(q2["final_answer"])
            st.caption(f"{q2['iterations']} laps · ${q2['usage']['cost_usd']:.6f} · "
                      f"{q2['usage']['wall_seconds']:.1f}s")
            render_mcp_steps(q2["steps"])

    st.divider()
    st.subheader("Requirement 5 — docstring + error rewrite, before vs after")
    err_before = load_json(str(MCP_DIR / "error_before.json"))
    err_after = load_json(str(MCP_DIR / "error_after.json"))
    if err_before and err_after:
        m1, m2, m3 = st.columns(3)
        m1.metric("Laps", err_after["iterations"],
                  delta=int(err_after["iterations"]) - int(err_before["iterations"]),
                  delta_color="inverse")
        m2.metric("Cost", f"${err_after['usage']['cost_usd']:.6f}",
                  delta=f"{err_after['usage']['cost_usd'] - err_before['usage']['cost_usd']:.6f}",
                  delta_color="inverse")
        m3.metric("Wall time", f"{err_after['usage']['wall_seconds']:.1f}s",
                  delta=f"{err_after['usage']['wall_seconds'] - err_before['usage']['wall_seconds']:.1f}s",
                  delta_color="inverse")
        col_before, col_after = st.columns(2)
        with col_before:
            st.markdown("### Before — `\"Error 3\"`")
            st.error(err_before["final_answer"])
            render_mcp_steps(err_before["steps"])
        with col_after:
            st.markdown("### After — recoverable error")
            st.success(err_after["final_answer"])
            render_mcp_steps(err_after["steps"])
    else:
        st.info("No `traces/mcp/error_before.json` / `error_after.json` found.")

    st.divider()
    st.subheader("Requirement 4 — raw JSON-RPC, annotated")
    wire = load_json(str(ROOT / "wire.json"))
    if wire:
        st.caption(wire.get("_readme", ""))
        for exchange in wire["exchanges"]:
            with st.expander(exchange["step"], expanded=False):
                st.markdown("**Request**")
                st.code(json.dumps(exchange["request"], indent=1), language="json")
                st.markdown("**Response**")
                st.code(json.dumps(exchange["response"], indent=1), language="json")
                if exchange.get("_annotations"):
                    st.markdown("**Annotations**")
                    for field, note in exchange["_annotations"].items():
                        st.write(f"- **{field}**: {note}")
        st.info(wire.get("_where_the_model_runs", ""))

    st.divider()
    st.subheader("Requirement 6 — the risk note")
    risk_file = ROOT / "risk_note.md"
    if risk_file.exists():
        st.markdown(risk_file.read_text(encoding="utf-8"))

    st.divider()
    st.subheader("Bonus — one gateway, one audit line, a scoped denial")
    gateway_run = load_json(str(MCP_DIR / "gateway_denial.json"))
    if gateway_run:
        st.write(f"**Q:** {gateway_run['question']}")
        st.info(gateway_run["final_answer"])
        st.caption(f"{gateway_run['iterations']} laps · "
                  f"${gateway_run['usage']['cost_usd']:.6f} · "
                  f"{gateway_run['usage']['wall_seconds']:.1f}s · token: claim-status-only")
        render_mcp_steps(gateway_run["steps"])
    else:
        st.info("No `traces/mcp/gateway_denial.json` found.")

    audit_file = MCP_DIR / "audit.jsonl"
    if audit_file.exists():
        st.markdown("**Audit log** — one line per `tools/call`, denials included:")
        rows = [json.loads(line) for line in audit_file.read_text(encoding="utf-8").splitlines()
               if line.strip()]
        display_rows = [{"ts": r["ts"], "caller": r["caller"], "tool": r["tool"],
                         "claim_number": r.get("claim_number") or "—",
                         "allowed": "✅" if r["allowed"] else "❌ denied"}
                        for r in rows]
        st.dataframe(display_rows, use_container_width=True, hide_index=True)


st.title("🏁 Claims Agent — Trace Viewer")
tab7, tab8, tab9 = st.tabs(["Week 7 — Agent vs Workflow", "Week 8 — Trajectory Eval",
                           "Week 9 — MCP"])
with tab7:
    render_week7_tab()
with tab8:
    render_week8_tab()
with tab9:
    render_week9_tab()
