#!/usr/bin/env python
"""Command-line entry point.

    python cli.py ingest                        # build the default index
    python cli.py ingest --all-sizes            # build every index in the sweep
    python cli.py ingest --corpus uploaded      # index documents you dropped in
    python cli.py ask "what is the compulsory deductible above 1500cc?"
    python cli.py ask "..." --no-rerank --top-k 3 --doc-type endorsement
    python cli.py status
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Ask-my-documents (local RAG)")
    parser.add_argument("--strategy", default=DEFAULT_CHUNKING.strategy,
                        choices=["fixed", "recursive", "heading"])
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

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
