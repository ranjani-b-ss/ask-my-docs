#!/usr/bin/env python
"""Command-line entry point.

    python cli.py ingest                        # build the default index
    python cli.py ingest --all-sizes            # build every index in the sweep
    python cli.py ingest --corpus uploaded      # index documents you dropped in
    python cli.py ask "what is the compulsory deductible above 1500cc?"
    python cli.py ask "..." --no-rerank --top-k 3 --doc-type endorsement
    python cli.py status
    python cli.py triage CLM-2026-00601          # the integrated system, end to end
    python cli.py trace cap_1a2b3c4d5e6f         # one request across the agent and MCP hops
"""

from __future__ import annotations

import argparse
import sys

from src.config import (
    CHUNK_SWEEP,
    DEFAULT_CHUNKING,
    DEFAULT_CORPUS,
    ChunkConfig,
    list_corpora,
)
from src import llm
from src.pipeline import ask, ingest
from src import store


def _cfg_from_args(args) -> ChunkConfig:
    return ChunkConfig(args.strategy, args.chunk_size, args.overlap)


def cmd_ingest(args) -> int:
    configs = CHUNK_SWEEP if args.all_sizes else [_cfg_from_args(args)]
    for cfg in configs:
        ingest(cfg, corpus_id=args.corpus)
        print()
    return 0


def cmd_ask(args) -> int:
    cfg = _cfg_from_args(args)
    if not store.collection_exists(cfg, args.corpus):
        print(f"No index for corpus '{args.corpus}' at '{cfg.describe()}'.\n"
              f"Run: python cli.py ingest --corpus {args.corpus}", file=sys.stderr)
        return 1

    result = ask(
        args.question,
        cfg=cfg,
        corpus_id=args.corpus,
        top_k=args.top_k,
        use_reranker=not args.no_rerank,
        doc_type=args.doc_type,
        effective_on_or_after=args.effective_after,
        model=args.model,
        provider=args.provider,
        force_extractive=args.no_llm,
        surface="cli",
    )

    print(f"\nQ: {args.question}\n")
    print(result.text)

    if result.citations:
        print("\nSources")
        for citation in result.citations:
            # `label` already ends in "p.N" when the source is a PDF — Hit.citation()
            # appends it — so don't add it a second time here.
            print(f"  [{citation['n']}] {citation['label']}")
            print(f"      {citation['document_id']} · effective {citation['effective_date'] or '?'} "
                  f"· score {citation['score']:.3f}")
            print(f"      {citation['relpath']}")

    print(f"\nmode={result.mode}  grounded={result.grounded}")
    print(f"diagnostics: {result.diagnostics}")
    if result.reason:
        print(f"note: {result.reason}")

    if args.show_chunks:
        print("\nRetrieved passages")
        for i, hit in enumerate(result.hits, start=1):
            print(f"\n--- [{i}] {hit.citation()}  cosine={hit.cosine} "
                  f"rerank={hit.rerank_score}")
            print(hit.text[:600])
    return 0


def cmd_status(args) -> int:
    print(f"Corpora available: {', '.join(list_corpora()) or '(none)'}")
    collections = store.list_collections()
    print("\nIndexes built:")
    if not collections:
        print("  (none — run: python cli.py ingest)")
    for name in sorted(collections):
        count = store.get_client().get_collection(name).count()
        print(f"  {name:<34} {count:>5} chunks")

    print("\nAnswer models:")
    active = llm.provider_name()
    for name in llm.PROVIDERS:
        st = llm.status(name)
        mark = "*" if name == active else " "
        state = "ready" if st.ready else "not configured"
        print(f"  {mark} {name:<10} {state:<15} {llm.default_model(name)}")
    print(f"\n  (* = active, from LLM_PROVIDER in .env)")
    if not llm.is_ready():
        print(f"\n  '{active}' is not usable, so answers fall back to retrieval-only mode")
        print(f"  (passages quoted verbatim). Reason: {llm.status(active).detail}")
    return 0


def cmd_triage(args) -> int:
    """The integrated system, end to end: claim number in, adjuster referral out. One trace id."""
    import json

    from src.agent import triage_agent

    result = triage_agent.triage(args.claim_number, provider=args.provider, model=args.model)
    packet = result["packet"]
    if args.json:
        print(json.dumps(packet, indent=2, default=str))
    else:
        print(f"claim {packet['claim_number']}  policy {packet['policy_number']}  "
              f"{packet['product']}  loss date {packet['loss_date']}")
        inf = packet["in_force"] or {}
        print(f"in force on loss date : {inf.get('in_force')}  — {inf.get('reason')}")
        print("facts:")
        for fact in packet["facts"]:
            print(f"  - {fact}")
        print("wording to weigh (resolved against the loss date):")
        for w in packet["wording"] or [{"role": "-", "citation": "(none cited)", "why": ""}]:
            print(f"  [{w['role']}] {w['citation']}")
            if w.get("why"):
                print(f"      why: {w['why']}")
        nums = packet["numbers"] or {}
        if nums:
            ded, cop = nums.get("deductible") or {}, nums.get("co_payment") or {}
            print("three numbers, kept separate:")
            print(f"  deductible   : {ded.get('amount', ded.get('reason', 'n/a'))}"
                  + (f"  ({ded['document_id']} v{ded['version']})" if ded.get("document_id") else ""))
            if cop:
                print(f"  co-payment   : {cop.get('percent')}%  applies={cop.get('applies')}"
                      f"  ({cop.get('document_id')} v{cop.get('version')})")
            for sl in nums.get("sub_limits", []):
                print(f"  sub-limit    : {sl['name']} = {sl.get('amount_per_day', sl['value'])}"
                      f"  ({sl['document_id']} v{sl['version']})")
            pl = nums.get("policy_limit") or {}
            print(f"  policy limit : {pl.get('amount')} ({pl.get('type')})")
        print(f"REFERRED TO {packet['referral'].get('queue', 'adjuster').upper()} "
              f"({packet['referral'].get('referral_id')}): {packet['referral'].get('reason')}")
        print(f"summary: {packet['summary_for_adjuster']}")
        print("decision: none — this system does not state a coverage decision")
    u = result["usage"]
    print(f"\ntrace {result['trace_id']}  |  {result['iterations']} laps, "
          f"{u['total_tokens']:,} tokens, ${u['cost_usd']:.5f}, {result['wall_seconds']:.1f}s  "
          f"|  guard: {len(result['guard_violations'])} violation(s), "
          f"{len(result['overrides'])} arg override(s), {len(result['blocked'])} blocked call(s)")
    print(f"        stopped: {result['stop_reason']}   (python cli.py trace {result['trace_id']})")
    return 0


def cmd_trace(args) -> int:
    from src import span_log

    out = span_log.stitch(args.trace_id)
    host = out["host"]
    if not host:
        print(f"no host trace {args.trace_id!r} in traces/capstone_traces.jsonl")
        return 1
    print(f"trace {args.trace_id}   claim {host['claim_number']}   prompt {host['prompt_version']}"
          f" ({host['prompt_sha']})   model {host['usage']['model']}")
    print(f"\n{'source':<22}{'what':<22}{'latency ms':>11}{'tokens in/out':>16}{'cost $':>10}")
    for sp in host["spans"]:
        if sp["kind"] == "llm":
            tok = f"{sp.get('prompt_tokens', 0)}/{sp.get('completion_tokens', 0)}"
            print(f"{'host':<22}{'llm lap ' + str(sp['lap']):<22}{sp['latency_ms']:>11}{tok:>16}"
                  f"{sp.get('cost_usd', 0):>10.5f}")
        else:
            tag = " BLOCKED" if sp.get("blocked") else (" FORCED" if sp.get("forced") else "")
            print(f"{'host':<22}{sp['tool'] + tag:<22}{sp['latency_ms']:>11}")
    for sp in out["server_spans"]:
        print(f"{sp['source']:<22}{sp['tool']:<22}{sp['latency_ms']:>11}")
    print("\nhop check (host dispatched vs. server recorded, same trace id):")
    for h in out["hops"]:
        print(f"  {h['tool']:<20} host {h['host_calls']}  server {h['server_spans']}  "
              f"{'ok' if h['matched'] else 'MISSING'}")
    print(f"trace id survived every hop: {out['complete']}")
    print(f"retrieved context (chunk -> sha): {host.get('retrieved_context')}")
    return 0 if out["complete"] else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask-my-documents (local RAG)")
    parser.add_argument("--strategy", default=DEFAULT_CHUNKING.strategy,
                        choices=["fixed", "recursive", "heading", "structured"])
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNKING.chunk_size)
    parser.add_argument("--overlap", type=int, default=DEFAULT_CHUNKING.overlap)
    parser.add_argument("--corpus", default=DEFAULT_CORPUS,
                        help="which directory under corpora/ to use")

    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="load, chunk, embed, store")
    p_ingest.add_argument("--all-sizes", action="store_true",
                          help="build every configuration in CHUNK_SWEEP")
    p_ingest.set_defaults(func=cmd_ingest)

    p_ask = sub.add_parser("ask", help="ask a question")
    p_ask.add_argument("question")
    p_ask.add_argument("--top-k", type=int, default=5)
    p_ask.add_argument("--no-rerank", action="store_true",
                       help="skip the cross-encoder (bi-encoder order only)")
    p_ask.add_argument("--no-llm", action="store_true",
                       help="force retrieval-only mode")
    p_ask.add_argument("--doc-type", default=None,
                       help="metadata filter: policy_wording | endorsement | all")
    p_ask.add_argument("--effective-after", default=None,
                       help="metadata filter: only docs effective on/after YYYY-MM-DD")
    # Default None, not a concrete model name: each provider has its own default, and
    # handing one provider's model id to another is a hard 400.
    p_ask.add_argument("--model", default=None,
                       help="override the provider's default model")
    p_ask.add_argument("--provider", default=None, choices=list(llm.PROVIDERS),
                       help="override LLM_PROVIDER from .env for this one call")
    p_ask.add_argument("--show-chunks", action="store_true")
    p_ask.set_defaults(func=cmd_ask)

    p_status = sub.add_parser("status", help="what is indexed, is Ollama up")
    p_status.set_defaults(func=cmd_status)

    p_triage = sub.add_parser("triage", help="triage one claim end to end (agent + MCP + logging)")
    p_triage.add_argument("claim_number", help="e.g. CLM-2026-00601 or C-005")
    p_triage.add_argument("--json", action="store_true", help="print the full packet as JSON")
    p_triage.add_argument("--model", default=None)
    p_triage.add_argument("--provider", default=None, choices=list(llm.PROVIDERS))
    p_triage.set_defaults(func=cmd_triage)

    p_trace = sub.add_parser("trace", help="show one request across the agent and MCP hops")
    p_trace.add_argument("trace_id")
    p_trace.set_defaults(func=cmd_trace)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
