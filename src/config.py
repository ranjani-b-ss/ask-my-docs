"""Central configuration. Every tunable knob the walkthrough talks about lives here."""

from __future__ import annotations

import os
from dataclasses import dataclass, asdict
from pathlib import Path

try:  # .env is convenience only; the app works with real environment variables alone.
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ModuleNotFoundError:
    pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CORPORA_DIR = PROJECT_ROOT / "corpora"

# The active corpus. Swap this (or pass --corpus) to point the app at a different document
# set; nothing else in the pipeline is topic-aware.
DEFAULT_CORPUS = "insurance"
UPLOAD_CORPUS = "uploaded"          # where documents added through the UI are written
DATA_DIR = CORPORA_DIR / DEFAULT_CORPUS
STORE_DIR = PROJECT_ROOT / ".chroma"

SUPPORTED_SUFFIXES = [".pdf", ".md", ".markdown", ".txt", ".html", ".htm"]


def corpus_dir(corpus_id: str) -> Path:
    return CORPORA_DIR / corpus_id


def list_corpora() -> list[str]:
    """Every directory under corpora/ that holds at least one loadable document."""
    if not CORPORA_DIR.exists():
        return []
    found = []
    for path in sorted(CORPORA_DIR.iterdir()):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if any(f.suffix.lower() in SUPPORTED_SUFFIXES for f in path.rglob("*")):
            found.append(path.name)
    return found

# --- Embeddings ---
# "local" runs bge-small via ONNX: free, offline, 384-dim, ~130MB downloaded once.
# "openai" uses text-embedding-3-small: 1536-dim, costs money, needs a key, and is a few
# points better on retrieval benchmarks. The reranker stays local either way — it is small
# and there is no hosted equivalent worth the latency.
EMBED_PROVIDER = os.environ.get("EMBED_PROVIDER", "local").strip().lower()
EMBED_MODEL = "BAAI/bge-small-en-v1.5"          # bi-encoder, 384-dim
OPENAI_EMBED_MODEL = "text-embedding-3-small"   # bi-encoder, 1536-dim
RERANK_MODEL = "Xenova/ms-marco-MiniLM-L-6-v2"  # cross-encoder, ~90MB

# BGE was trained with an instruction prefix on the query side only. Using it lifts
# retrieval quality by a few points and costs nothing. See README "Asymmetric search".
BGE_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

# --- Generation ---
# "ollama" (local, free, no key) or "openai" / "anthropic" / "gemini" (hosted, each needs
# its own key in .env). If the selected provider is unreachable the app degrades to
# retrieval-only mode and quotes the winning passage instead of writing prose.
LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "ollama").strip().lower()

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434").strip()
# 3b is the right default on a CPU-only machine (any Intel Mac). On Apple Silicon or a
# discrete GPU, "llama3.1:8b" follows the citation format noticeably better.
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b").strip()
OLLAMA_TIMEOUT = 300   # CPU-only inference on a mid-range desktop CPU is slow, not broken

OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip()
OPENAI_TIMEOUT = 60

ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-opus-5").strip()
# Claude Opus 5 thinks by default, and max_tokens bounds thinking AND the answer together.
# Sizing this for the answer alone truncates mid-sentence.
ANTHROPIC_MAX_TOKENS = 8000

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
# An alias, deliberately, not a pinned version: Google gates older concrete versions to
# existing users, so a pinned id that works today 404s for a key created tomorrow.
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-latest").strip()
GEMINI_TIMEOUT = 60

# --- Retrieval ---
TOP_K = 5          # chunks handed to the model after reranking
CANDIDATE_K = 20   # chunks pulled from the vector store before reranking

# The abstain gate. Calibrated by eval/calibrate.py against this corpus, NOT guessed:
# BGE cosine similarity for unrelated text sits around 0.50-0.55, so a naive 0.5
# threshold would never abstain. The cross-encoder score is the more decisive signal.
# Swept over 39 gold questions spanning two very different corpora — clean synthetic
# Markdown and a real 21-page LIC policy PDF. This pair scores 36/39 on both together:
# 24/25 answerable kept, 12/14 unanswerable refused. Re-measure with eval/calibrate.py if
# you swap in a corpus that behaves differently.
#
# Two things the sweep showed, worth knowing before you tune:
#   * The cosine gate does little work. 0.55 through 0.62 give identical results; only 0.64
#     helps. The reranker is what actually separates answerable from not.
#   * Rerank 0.02 keeps one more real answer; 0.10 refuses one more non-answer. 0.10 wins
#     here because a confident wrong answer costs more than a refusal.
MIN_COSINE = 0.64
MIN_RERANK_SCORE = 0.10

# These two are only the FALLBACK. Thresholds are a measured property of a corpus, not
# universal constants — a cross-encoder scores clean Markdown far higher than the same
# content pulled out of a real PDF. Each corpus therefore calibrates its own values at
# ingest time (src/calibration.py) and stores them on the collection; these apply only to a
# corpus that has not been calibrated. Nothing here is document-specific.


# Cross-encoder scores within this band count as a tie, and the later effective_date wins.
# An amending clause and the clause it amends read almost identically to the reranker, so
# without this the superseded figure often reaches the model first. See retriever.retrieve.
RECENCY_TIE_BAND = 0.05


@dataclass(frozen=True)
class ChunkConfig:
    """One chunking strategy. The eval harness sweeps several of these."""

    strategy: str = "recursive"   # "fixed" | "recursive" | "heading"
    chunk_size: int = 800         # target characters per chunk
    overlap: int = 150            # characters repeated between neighbours

    @property
    def slug(self) -> str:
        return f"{self.strategy}_{self.chunk_size}_{self.overlap}"

    def describe(self) -> str:
        return f"{self.strategy}, {self.chunk_size} chars, {self.overlap} overlap"

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_CHUNKING = ChunkConfig()

# The configurations compared in eval/run_eval.py. Deliberately spans "too small to hold
# a complete clause" through "so big the answer is buried in noise".
CHUNK_SWEEP = [
    ChunkConfig("fixed", 300, 0),
    ChunkConfig("recursive", 300, 60),
    ChunkConfig("recursive", 800, 150),
    ChunkConfig("recursive", 1600, 200),
    ChunkConfig("heading", 2000, 0),
]
