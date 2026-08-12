"""Stage 2 — split documents into chunks.

Three strategies, deliberately different in kind rather than only in size:

``fixed``      Cut every N characters. Ignores structure entirely. The naive baseline —
               it will happily slice a sentence, a number, or a table row in half.
``recursive``  Split on the biggest natural boundary that fits (blank line, then line,
               then sentence, then word), then pack pieces up to the target size.
               This is what most production RAG systems do.
``heading``    One chunk per Markdown/HTML heading section, so a clause stays whole.
               Structure-aware and great for policy documents, but chunk sizes become
               uneven, and one long section can still overflow.

Two details that matter more than chunk size, and which the README expands on:

1. **Overlap** repeats the tail of one chunk at the head of the next, so a fact that
   straddles a boundary survives in at least one chunk intact.
2. **Contextual headers.** We embed each chunk with its document title and heading trail
   prepended ("Own Damage Section > 2.2 Compulsory deductible"). A bare chunk saying
   "INR 3,000" is nearly unretrievable; the same chunk labelled with its clause is easy to
   find. ``Chunk.text`` keeps the original for display, ``Chunk.embed_text`` carries the
   header used for the embedding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import ChunkConfig
from .loader import LoadedDoc

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")


@dataclass
class Chunk:
    text: str
    embed_text: str
    meta: dict = field(default_factory=dict)

    @property
    def chunk_id(self) -> str:
        return f"{self.meta['document_id']}::{self.meta['chunk_index']}"

    def citation(self) -> str:
        bits = [self.meta.get("title") or self.meta["document_id"]]
        if self.meta.get("section"):
            bits.append(self.meta["section"])
        if self.meta.get("page"):
            bits.append(f"p.{self.meta['page']}")
        return " > ".join(bits)


# --------------------------------------------------------------------------- splitters


def _split_fixed(text: str, size: int, overlap: int) -> list[tuple[int, str]]:
    step = max(1, size - overlap)
    out = []
    for start in range(0, len(text), step):
        piece = text[start:start + size]
        if piece.strip():
            out.append((start, piece))
        if start + size >= len(text):
            break
    return out


def _atoms(text: str) -> list[str]:
    """Break text into the smallest units we are willing to keep together."""
    atoms: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        block = block.strip("\n")
        if not block.strip():
            continue
        # Keep table blocks whole: a row divorced from its header row is useless.
        if block.count("|") >= 2 and block.count("\n") >= 1:
            atoms.append(block)
            continue
        for line in block.split("\n"):
            if len(line) <= 400:
                atoms.append(line)
            else:
                atoms.extend(s for s in _SENTENCE_END.split(line) if s.strip())
        atoms.append("")  # paragraph marker, preserves blank line on rejoin
    return atoms


def _pack_within_section(
    body: str, offset: int, section: str, size: int, overlap: int
) -> list[tuple[int, str, str]]:
    """Split one section's body into <= ``size`` pieces on natural boundaries."""
    if len(body) <= size:
        return [(offset, section, body)]

    out: list[tuple[int, str, str]] = []
    buf: list[str] = []
    buf_len = 0
    cursor = offset

    def flush() -> None:
        nonlocal buf, buf_len, cursor
        text = "\n".join(buf).strip()
        if not text:
            buf, buf_len = [], 0
            return
        out.append((cursor, section, text))
        if overlap > 0:
            tail = text[-overlap:]
            cursor += max(0, len(text) - overlap)
            buf, buf_len = [tail], len(tail)
        else:
            cursor += len(text)
            buf, buf_len = [], 0

    for atom in _atoms(body):
        # A single atom larger than the target (a very wide table) must be hard-split.
        if len(atom) > size:
            flush()
            for _, piece in _split_fixed(atom, size, overlap):
                out.append((cursor, section, piece))
            cursor += len(atom)
            continue
        if buf_len + len(atom) + 1 > size and buf_len > 0:
            flush()
        buf.append(atom)
        buf_len += len(atom) + 1

    flush()
    return [(o, s, t) for o, s, t in out if t.strip()]


def _split_recursive(text: str, size: int, overlap: int) -> list[tuple[int, str, str]]:
    """Section-aware packing.

    Headings are treated as hard boundaries, because a heading stranded at the tail of one
    chunk while its content opens the next is the single most damaging chunking mistake:
    the chunk gets labelled with the *previous* section, and the passage that truly answers
    the question becomes unfindable. (This exact bug cost the per-diem query its answer
    before the splitter became section-aware — see README, "What went wrong".)

    Whole sections are then packed together while they fit, so ``chunk_size`` still
    controls how much context travels with each fact.
    """
    sections = _sections(text)
    out: list[tuple[int, str, str]] = []

    buf: list[str] = []
    buf_len = 0
    buf_offset: int | None = None
    buf_section = ""

    def flush() -> None:
        nonlocal buf, buf_len, buf_offset, buf_section
        if not buf:
            return
        body = "\n\n".join(buf).strip()
        if body:
            out.append((buf_offset or 0, buf_section, body))
        buf, buf_len, buf_offset, buf_section = [], 0, None, ""

    for offset, section, body in sections:
        if len(body) > size:
            flush()
            out.extend(_pack_within_section(body, offset, section, size, overlap))
            continue
        if buf_len + len(body) + 2 > size and buf_len > 0:
            flush()
        if buf_offset is None:
            buf_offset, buf_section = offset, section
        buf.append(body)
        buf_len += len(body) + 2

    flush()
    return out


def _sections(text: str) -> list[tuple[int, str, str]]:
    """Return (offset, heading_trail, body) for each heading section."""
    matches = list(_HEADING.finditer(text))
    if not matches:
        return [(0, "", text)]

    sections: list[tuple[int, str, str]] = []
    if matches[0].start() > 0:
        preamble = text[: matches[0].start()]
        if preamble.strip():
            sections.append((0, "", preamble))

    trail: list[str] = []
    for i, match in enumerate(matches):
        level = len(match.group(1))
        heading = match.group(2).strip()
        trail = trail[: level - 1]
        while len(trail) < level - 1:
            trail.append("")
        trail.append(heading)

        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.start():end].strip()
        if body:
            sections.append((match.start(), " > ".join(t for t in trail if t), body))
    return sections


# ------------------------------------------------------------------------------ public


def chunk_document(doc: LoadedDoc, cfg: ChunkConfig, start_index: int = 0) -> list[Chunk]:
    title = doc.meta.get("title", doc.meta["document_id"])
    pieces: list[tuple[int, str, str]] = []  # (offset, section, text)

    if cfg.strategy == "heading":
        # One chunk per heading section; oversized sections are packed down further.
        for offset, section, body in _sections(doc.text):
            pieces.extend(
                _pack_within_section(body, offset, section, cfg.chunk_size, cfg.overlap)
            )
    elif cfg.strategy == "recursive":
        pieces.extend(_split_recursive(doc.text, cfg.chunk_size, cfg.overlap))
    else:
        # "fixed" deliberately ignores document structure — it is the naive baseline the
        # eval compares against. Section is recovered by offset lookup so citations still
        # name a clause, but a chunk may straddle two sections and be mislabelled.
        sections = _sections(doc.text)
        for offset, body in _split_fixed(doc.text, cfg.chunk_size, cfg.overlap):
            section = ""
            for sec_offset, sec_name, _ in sections:
                if sec_offset <= offset:
                    section = sec_name
                else:
                    break
            pieces.append((offset, section, body))

    chunks: list[Chunk] = []
    for i, (offset, section, body) in enumerate(pieces):
        meta = dict(doc.meta)
        meta.update(
            chunk_index=start_index + i,
            section=section,
            char_start=offset,
            char_end=offset + len(body),
            n_chars=len(body),
            chunk_strategy=cfg.strategy,
            chunk_size=cfg.chunk_size,
            chunk_overlap=cfg.overlap,
        )
        page = doc.page_for_offset(offset)
        if page is not None:
            meta["page"] = page

        header = f"{title}" + (f" > {section}" if section else "")
        chunks.append(Chunk(text=body, embed_text=f"[{header}]\n{body}", meta=meta))
    return chunks


def chunk_corpus(docs: list[LoadedDoc], cfg: ChunkConfig) -> list[Chunk]:
    out: list[Chunk] = []
    for doc in docs:
        out.extend(chunk_document(doc, cfg, start_index=0))
    return out


def chunk_stats(chunks: list[Chunk]) -> dict:
    sizes = sorted(c.meta["n_chars"] for c in chunks)
    if not sizes:
        return {"count": 0}
    return {
        "count": len(sizes),
        "min": sizes[0],
        "median": sizes[len(sizes) // 2],
        "max": sizes[-1],
        "mean": round(sum(sizes) / len(sizes)),
        "total_chars": sum(sizes),
    }
