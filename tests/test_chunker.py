"""src/chunker.py — the "fixed" strategy's overlap and the id/citation contracts every other
part of the retrieval pipeline relies on. Not testing embedding quality here (that needs the
real ONNX models) — just the deterministic text-splitting logic underneath it.
"""

from __future__ import annotations

from src.chunker import chunk_document
from src.config import ChunkConfig
from src.loader import LoadedDoc

LONG_TEXT = (
    "Alpha section text repeated many times so the fixed splitter has more than one chunk "
    "to produce from it. " * 20
)


def _doc(text: str, document_id: str = "TEST-DOC-001") -> LoadedDoc:
    return LoadedDoc(text=text, meta={"document_id": document_id})


def test_chunk_document_produces_at_least_one_chunk():
    cfg = ChunkConfig(strategy="fixed", chunk_size=200, overlap=20)
    chunks = chunk_document(_doc("short document text"), cfg)
    assert len(chunks) >= 1


def test_chunk_id_matches_document_id_and_index():
    cfg = ChunkConfig(strategy="fixed", chunk_size=200, overlap=20)
    chunks = chunk_document(_doc(LONG_TEXT), cfg)
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_id == f"TEST-DOC-001::{i}"


def test_chunk_start_index_offsets_the_chunk_ids():
    """chunk_corpus relies on start_index to keep ids unique across documents in one corpus."""
    cfg = ChunkConfig(strategy="fixed", chunk_size=200, overlap=20)
    chunks = chunk_document(_doc(LONG_TEXT), cfg, start_index=5)
    assert chunks[0].chunk_id == "TEST-DOC-001::5"


def test_fixed_strategy_overlap_actually_overlaps():
    """The tail of one chunk must reappear at the head of the next — that's the entire point
    of overlap, and it's easy to get the step arithmetic off by one."""
    cfg = ChunkConfig(strategy="fixed", chunk_size=100, overlap=20)
    chunks = chunk_document(_doc(LONG_TEXT), cfg)
    assert len(chunks) >= 2
    for a, b in zip(chunks, chunks[1:]):
        tail_of_a = a.text[-20:]
        assert tail_of_a in b.text, "expected the overlap window to reappear in the next chunk"


def test_zero_overlap_means_no_shared_text():
    cfg = ChunkConfig(strategy="fixed", chunk_size=100, overlap=0)
    chunks = chunk_document(_doc(LONG_TEXT), cfg)
    assert len(chunks) >= 2
    # With zero overlap, consecutive chunks should be contiguous, non-repeating slices.
    combined = "".join(c.text for c in chunks)
    assert combined.startswith(LONG_TEXT[: len(combined)])


def test_embed_text_carries_the_document_title_header():
    """A bare chunk saying a number is unretrievable without its heading context — see the
    module docstring's own justification for embed_text existing at all."""
    cfg = ChunkConfig(strategy="fixed", chunk_size=200, overlap=20)
    doc = LoadedDoc(text="INR 3,000 is the deductible.",
                    meta={"document_id": "TEST-DOC-001", "title": "Motor Policy"})
    chunks = chunk_document(doc, cfg)
    assert chunks[0].embed_text.startswith("[Motor Policy]")


def test_recursive_strategy_respects_target_size_roughly():
    cfg = ChunkConfig(strategy="recursive", chunk_size=100, overlap=20)
    chunks = chunk_document(_doc(LONG_TEXT), cfg)
    assert len(chunks) >= 2
    # Recursive packing targets chunk_size but may exceed it slightly to avoid mid-sentence
    # cuts — allow generous headroom rather than asserting an exact byte count.
    for c in chunks:
        assert len(c.text) <= cfg.chunk_size * 2
