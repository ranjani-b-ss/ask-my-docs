"""Ties the six stages together: ingest once, then ask many times."""

from __future__ import annotations

import time
from pathlib import Path

from .chunker import chunk_corpus, chunk_stats
from .config import (
    CANDIDATE_K,
    DEFAULT_CHUNKING,
    DEFAULT_CORPUS,
    MIN_COSINE,
    MIN_RERANK_SCORE,
    OLLAMA_MODEL,
    SUPPORTED_SUFFIXES,
    TOP_K,
    ChunkConfig,
    corpus_dir,
)
from .embedder import get_embedder
from .generator import Answer, answer_from_retrieval
from .loader import SIDECAR_NAME, load_corpus
from .retriever import build_where, retrieve
from . import store, trace


def ingest(
    cfg: ChunkConfig = DEFAULT_CHUNKING,
    corpus_id: str = DEFAULT_CORPUS,
    data_dir: Path | None = None,
    verbose: bool = True,
) -> dict:
    """Load -> chunk -> embed -> store. Rebuilds this corpus+config collection from scratch."""
    root = data_dir or corpus_dir(corpus_id)
    docs = load_corpus(root)
    if not docs:
        raise SystemExit(f"No supported documents found under {root}")

    chunks = chunk_corpus(docs, cfg)
    if not chunks:
        raise SystemExit("Documents loaded but produced zero chunks.")

    embedder = get_embedder()
    vectors = embedder.embed_passages([c.embed_text for c in chunks])

    collection = store.reset_collection(cfg, corpus_id)
    store.add_chunks(collection, chunks, vectors)

    stats = chunk_stats(chunks)
    report = {
        "corpus": corpus_id,
        "config": cfg.describe(),
        "documents": len(docs),
        "chunks": stats["count"],
        "chunk_chars_min": stats["min"],
        "chunk_chars_median": stats["median"],
        "chunk_chars_max": stats["max"],
        "embedding_dim": embedder.dim,
        "collection": store.collection_name(cfg, corpus_id),
        "files": [
            {
                "filename": d.meta["filename"],
                "chars": len(d.text),
                "doc_type": d.meta.get("doc_type", "?"),
                "effective_date": d.meta.get("effective_date") or "",
                "document_id": d.meta.get("document_id", "?"),
            }
            for d in docs
        ],
    }

    if verbose:
        print(f"Ingested {len(docs)} documents -> {stats['count']} chunks  "
              f"[{corpus_id} · {cfg.describe()}]")
        for f in report["files"]:
            print(f"  - {f['filename']:<38} {f['chars']:>7,} chars  "
                  f"({f['doc_type']}, eff. {f['effective_date'] or '?'})")
        print(f"  chunk chars: min {stats['min']}, median {stats['median']}, "
              f"max {stats['max']}")
        print(f"  vectors: {stats['count']} x {embedder.dim}  -> collection "
              f"'{report['collection']}'")

    return report


def save_uploads(files: list[tuple[str, bytes]], corpus_id: str, replace: bool = True) -> list[str]:
    """Write uploaded documents into corpora/<corpus_id>/ and return the accepted names.

    ``replace`` clears out the previous documents, which is almost always what someone wants
    when uploading a fresh set — otherwise yesterday's document silently stays searchable
    and can answer today's question.

    It deletes only the *documents*, never ``metadata.yaml``. Wiping the whole directory
    would silently destroy the hand-written metadata that citations and date filtering
    depend on, and the only symptom would be citations quietly degrading to whatever the
    PDF claims about itself.
    """
    root = corpus_dir(corpus_id)
    if replace and root.exists():
        for existing in root.rglob("*"):
            if existing.is_file() and existing.name != SIDECAR_NAME:
                existing.unlink()
    root.mkdir(parents=True, exist_ok=True)

    accepted: list[str] = []
    for name, payload in files:
        safe_name = Path(name).name
        if Path(safe_name).suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        (root / safe_name).write_bytes(payload)
        accepted.append(safe_name)
    return accepted


def ask(
    question: str,
    cfg: ChunkConfig = DEFAULT_CHUNKING,
    corpus_id: str = DEFAULT_CORPUS,
    top_k: int = TOP_K,
    candidate_k: int = CANDIDATE_K,
    use_reranker: bool = True,
    doc_type: str | None = None,
    effective_on_or_after: str | None = None,
    min_cosine: float | None = None,
    min_rerank_score: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    force_extractive: bool = False,
    use_hybrid: bool = True,
    surface: str = "cli",
    trace_it: bool = True,
) -> Answer:
    started = time.perf_counter()
    where = build_where(doc_type, effective_on_or_after)
    retrieval = retrieve(
        question,
        cfg=cfg,
        corpus_id=corpus_id,
        top_k=top_k,
        candidate_k=candidate_k,
        use_reranker=use_reranker,
        where=where,
        min_cosine=min_cosine,
        min_rerank_score=min_rerank_score,
        use_hybrid=use_hybrid,
    )
    answer = answer_from_retrieval(
        retrieval, model=model, provider=provider, force_extractive=force_extractive
    )
    if trace_it:
        _trace(question, answer, retrieval, cfg, corpus_id, top_k, candidate_k,
               use_reranker, use_hybrid, where, min_cosine, min_rerank_score,
               surface, int((time.perf_counter() - started) * 1000))
    return answer


def _trace(question, answer, retrieval, cfg, corpus_id, top_k, candidate_k, use_reranker,
           use_hybrid, where, min_cosine, min_rerank_score, surface, latency_ms) -> None:
    """Write one trace row. Never allowed to break a request.

    A logging failure that takes down the answer would be a worse bug than the one the log
    exists to find, so this swallows its own errors and says so on stderr.
    """
    d = answer.diagnostics or {}
    try:
        trace.record(
            question=question,
            corpus=corpus_id,
            surface=surface,
            chunking=cfg.to_dict(),
            collection=d.get("collection", ""),
            top_k=top_k,
            candidate_k=candidate_k,
            use_reranker=use_reranker,
            use_hybrid=bool(d.get("hybrid", use_hybrid)),
            where=where,
            min_cosine=MIN_COSINE if min_cosine is None else min_cosine,
            min_rerank_score=(
                MIN_RERANK_SCORE if min_rerank_score is None else min_rerank_score
            ),
            retrieved=[
                {
                    "rank": i,
                    "chunk_id": h.chunk_id,
                    "document_id": h.meta.get("document_id"),
                    "section": h.meta.get("section") or None,
                    "page": h.meta.get("page"),
                    "effective_date": h.meta.get("effective_date") or None,
                    "cosine": h.cosine,
                    "rerank": h.rerank_score,
                    "bm25": h.bm25,
                    "rrf": h.rrf,
                }
                for i, h in enumerate(retrieval.hits, start=1)
            ],
            candidates=d.get("candidates", 0),
            keyword_only_candidates=d.get("keyword_only_candidates", 0),
            prompt_version=d.get("prompt_version", ""),
            prompt_sha=d.get("prompt_sha", ""),
            context_sha=d.get("context_sha") or "",
            provider=d.get("provider") or "",
            model=d.get("model") or "",
            params=d.get("params") or {},
            raw_output=d.get("raw_output"),
            gate=d.get("gate", ""),
            gate_detail=(answer.reason or retrieval.reason or "")[:500],
            grounded=answer.grounded,
            mode=answer.mode,
            answer=answer.text,
            citations=[
                {"n": c["n"], "label": c["label"], "document_id": c["document_id"],
                 "section": c.get("section"), "page": c.get("page")}
                for c in answer.citations
            ],
            latency_ms=latency_ms,
            error=d.get("error"),
        )
    except Exception as exc:                       # pragma: no cover
        print(f"! trace write failed: {exc}")
