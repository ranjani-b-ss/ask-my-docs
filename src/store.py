"""Stage 4 — the vector store.

Chroma keeps the chunk vectors in an **HNSW** index. Comparing a query against every
vector one by one is exact but linear; HNSW builds a navigable graph of vectors so a
search visits a few hundred nodes instead of the whole collection. It is *approximate* —
in exchange for being orders of magnitude faster it may occasionally miss a true nearest
neighbour, which is a trade every production vector database makes.

One collection per chunking configuration. That is what lets the eval harness hold five
chunk sizes side by side and query each independently, instead of re-ingesting between
measurements.
"""

from __future__ import annotations

import re

import chromadb
from chromadb.config import Settings

from .chunker import Chunk
from .config import DEFAULT_CORPUS, STORE_DIR, ChunkConfig

_client: chromadb.ClientAPI | None = None


def get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(STORE_DIR),
            settings=Settings(anonymized_telemetry=False, allow_reset=True),
        )
    return _client


def safe_corpus_id(name: str) -> str:
    """Chroma names allow [a-zA-Z0-9._-] only, and must start/end alphanumeric."""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return (cleaned or "corpus")[:24]


def collection_name(cfg: ChunkConfig, corpus_id: str = DEFAULT_CORPUS) -> str:
    """Collections are scoped by corpus AND chunk config.

    Scoping by corpus keeps an uploaded document set from being searched alongside the
    placeholder pack — otherwise a question about the user's own PDF could be answered
    from sample data, which is exactly the failure this whole app exists to prevent.

    The embedding model is in the name too, because vectors from different models are not
    comparable and their dimensions differ. Switching EMBED_PROVIDER therefore builds a
    fresh index instead of corrupting the existing one.
    """
    from .embedder import embed_model_tag

    return f"{safe_corpus_id(corpus_id)}_{embed_model_tag()}_{cfg.slug}"


def reset_collection(cfg: ChunkConfig, corpus_id: str = DEFAULT_CORPUS):
    client = get_client()
    name = collection_name(cfg, corpus_id)
    try:
        client.delete_collection(name)
    except Exception:
        pass  # first run: nothing to delete
    return client.create_collection(
        name=name,
        # Cosine distance, so "distance 0" means identical direction. Chroma's default is
        # squared L2, which is harder to reason about when setting a similarity threshold.
        metadata={"hnsw:space": "cosine", "corpus": corpus_id, **cfg.to_dict()},
    )


def get_collection(cfg: ChunkConfig, corpus_id: str = DEFAULT_CORPUS):
    return get_client().get_collection(collection_name(cfg, corpus_id))


def collection_exists(cfg: ChunkConfig, corpus_id: str = DEFAULT_CORPUS) -> bool:
    return collection_name(cfg, corpus_id) in list_collections()


def drop_corpus(corpus_id: str) -> int:
    """Delete every index built for a corpus, across all chunk configs."""
    prefix = safe_corpus_id(corpus_id) + "_"
    dropped = 0
    for name in list_collections():
        if name.startswith(prefix):
            get_client().delete_collection(name)
            dropped += 1
    return dropped


def list_collections() -> list[str]:
    return [c.name for c in get_client().list_collections()]


def add_chunks(collection, chunks: list[Chunk], embeddings, batch_size: int = 256) -> None:
    for start in range(0, len(chunks), batch_size):
        window = chunks[start:start + batch_size]
        collection.add(
            ids=[c.chunk_id for c in window],
            embeddings=[embeddings[start + i].tolist() for i in range(len(window))],
            documents=[c.text for c in window],
            metadatas=[c.meta for c in window],
        )


def query(collection, query_vector, n_results: int, where: dict | None = None) -> list[dict]:
    """Return candidates ordered by similarity, with cosine similarity already converted."""
    result = collection.query(
        query_embeddings=[query_vector.tolist()],
        n_results=min(n_results, max(1, collection.count())),
        where=where or None,
        include=["documents", "metadatas", "distances"],
    )
    hits: list[dict] = []
    for chunk_id, doc, meta, distance in zip(
        result["ids"][0], result["documents"][0], result["metadatas"][0], result["distances"][0]
    ):
        hits.append(
            {
                # Carried all the way to the trace file. Without a stable id a trace can
                # record *that* five passages were used but not *which*, and replaying it
                # would mean re-running the search and hoping for the same result.
                "chunk_id": chunk_id,
                "text": doc,
                "meta": meta,
                # Chroma reports cosine *distance*; similarity is 1 - distance.
                "cosine": round(1.0 - float(distance), 4),
            }
        )
    return hits


def get_by_ids(collection, chunk_ids: list[str]) -> dict[str, dict]:
    """Fetch chunks by id, for replaying a trace without re-running retrieval."""
    if not chunk_ids:
        return {}
    got = collection.get(ids=chunk_ids, include=["documents", "metadatas"])
    return {
        cid: {"text": text, "meta": meta}
        for cid, text, meta in zip(got["ids"], got["documents"], got["metadatas"])
    }
