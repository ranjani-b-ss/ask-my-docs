"""Stage 3 — embeddings.

An embedding turns a piece of text into a fixed-length list of numbers (384 of them for
bge-small) positioned so that texts with similar *meaning* land near each other. That is
what lets "how long do I have to file a claim?" match a passage that says "submission
window is 21 days" without sharing a single keyword.

Two model types appear here, and the difference is the ``bi-encoder vs cross-encoder``
topic on the syllabus:

**Bi-encoder** (``Embedder``) encodes the query and each chunk *separately*. Because
chunk vectors can be computed once at ingest time and reused, it scales to millions of
chunks — but the query never "sees" the chunk, so scoring is approximate.

**Cross-encoder** (``Reranker``) feeds the query and one chunk through the model
*together* and outputs a single relevance score. Far more accurate, far too slow to run
over the whole corpus. So: retrieve ~20 candidates with the bi-encoder, then rescore just
those 20 with the cross-encoder. Best of both.
"""

from __future__ import annotations

import os
import re

import numpy as np
import requests
from fastembed import TextEmbedding
from fastembed.rerank.cross_encoder import TextCrossEncoder

from .config import (
    BGE_QUERY_PREFIX,
    EMBED_MODEL,
    EMBED_PROVIDER,
    OPENAI_BASE_URL,
    OPENAI_EMBED_MODEL,
    RERANK_MODEL,
)

_embedder: dict[str, "Embedder | OpenAIEmbedder"] = {}
_reranker: dict[str, "Reranker"] = {}


def _l2_normalise(vectors: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    return vectors / np.clip(norms, 1e-12, None)


class Embedder:
    """Bi-encoder. Loaded once and cached; the ONNX weights download on first use."""

    def __init__(self, model_name: str = EMBED_MODEL):
        self.model_name = model_name
        self._model = TextEmbedding(model_name)
        self.dim = len(next(iter(self._model.embed(["dimension probe"]))))

    def embed_passages(self, texts: list[str], batch_size: int = 64) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        vectors = np.asarray(
            list(self._model.embed(texts, batch_size=batch_size)), dtype=np.float32
        )
        return _l2_normalise(vectors)

    def embed_query(self, text: str) -> np.ndarray:
        """BGE was trained with an instruction prefix on queries only — asymmetric search.

        Skipping the prefix still works, but measurably worse. Passages get no prefix.
        """
        prefixed = BGE_QUERY_PREFIX + text if "bge" in self.model_name.lower() else text
        vector = np.asarray(
            list(self._model.embed([prefixed]))[0], dtype=np.float32
        ).reshape(1, -1)
        return _l2_normalise(vector)[0]


class Reranker:
    """Cross-encoder. Scores are raw logits, so we squash them to 0-1 for a stable gate."""

    def __init__(self, model_name: str = RERANK_MODEL):
        self.model_name = model_name
        self._model = TextCrossEncoder(model_name)

    def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        logits = list(self._model.rerank(query, passages))
        return [float(1.0 / (1.0 + np.exp(-x))) for x in logits]


class OpenAIEmbedder:
    """Hosted bi-encoder. Same interface as ``Embedder``, 1536 dimensions.

    Note there is no query prefix here: OpenAI's embedding models are trained
    symmetrically, so queries and passages are encoded identically. Adding BGE's
    instruction prefix would actively hurt.
    """

    dim = 1536

    def __init__(self, model_name: str = OPENAI_EMBED_MODEL):
        self.model_name = model_name

    def _post(self, texts: list[str]) -> np.ndarray:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "EMBED_PROVIDER=openai but OPENAI_API_KEY is not set. Add it to .env."
            )
        response = requests.post(
            f"{OPENAI_BASE_URL}/embeddings",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={"model": self.model_name, "input": texts},
            timeout=60,
        )
        response.raise_for_status()
        rows = sorted(response.json()["data"], key=lambda d: d["index"])
        return np.asarray([r["embedding"] for r in rows], dtype=np.float32)

    def embed_passages(self, texts: list[str], batch_size: int = 128) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        out = [
            self._post(texts[i:i + batch_size]) for i in range(0, len(texts), batch_size)
        ]
        return _l2_normalise(np.vstack(out))

    def embed_query(self, text: str) -> np.ndarray:
        return _l2_normalise(self._post([text]))[0]


def get_embedder(model_name: str | None = None) -> Embedder | OpenAIEmbedder:
    """Returns whichever bi-encoder EMBED_PROVIDER selects, cached per model."""
    if EMBED_PROVIDER == "openai":
        name = model_name or OPENAI_EMBED_MODEL
        if name not in _embedder:
            _embedder[name] = OpenAIEmbedder(name)
        return _embedder[name]

    name = model_name or EMBED_MODEL
    if name not in _embedder:
        _embedder[name] = Embedder(name)
    return _embedder[name]


def embed_model_tag() -> str:
    """Short, filesystem-safe id for the active embedding model.

    This goes into the Chroma collection name. Without it, switching EMBED_PROVIDER would
    try to query a 384-dim index with a 1536-dim vector — Chroma would either error or,
    worse, silently return nonsense.
    """
    name = OPENAI_EMBED_MODEL if EMBED_PROVIDER == "openai" else EMBED_MODEL
    return re.sub(r"[^a-z0-9]+", "", name.split("/")[-1].lower())[:14]


def get_reranker(model_name: str = RERANK_MODEL) -> Reranker:
    if model_name not in _reranker:
        _reranker[model_name] = Reranker(model_name)
    return _reranker[model_name]
