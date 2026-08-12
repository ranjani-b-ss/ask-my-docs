"""Ties the six stages together: ingest once, then ask many times."""

from __future__ import annotations

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
from . import store


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
) -> Answer:
    retrieval = retrieve(
        question,
        cfg=cfg,
        corpus_id=corpus_id,
        top_k=top_k,
        candidate_k=candidate_k,
        use_reranker=use_reranker,
        where=build_where(doc_type, effective_on_or_after),
        min_cosine=min_cosine,
        min_rerank_score=min_rerank_score,
    )
    return answer_from_retrieval(
        retrieval, model=model, provider=provider, force_extractive=force_extractive
    )
