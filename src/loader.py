"""Stage 1 — load documents.

Turns files of three different shapes (Markdown, PDF, HTML) into one uniform
``LoadedDoc``. Everything downstream is format-blind, which is why adding a new
format later means touching only this file.

Each document keeps the metadata needed to *cite* it later: a stable id, a title,
an effective date, and a source URL.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from pypdf import PdfReader


@dataclass
class LoadedDoc:
    text: str
    meta: dict = field(default_factory=dict)
    # Maps a character offset in ``text`` -> page number. PDFs only; empty otherwise.
    page_breaks: list[tuple[int, int]] = field(default_factory=list)

    def page_for_offset(self, offset: int) -> int | None:
        page = None
        for start, page_no in self.page_breaks:
            if start <= offset:
                page = page_no
            else:
                break
        return page


_FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _normalise_meta(raw: dict, path: Path) -> dict:
    """Chroma only accepts str/int/float/bool metadata values, so flatten everything."""
    # Resolve first: Path.as_uri() raises on a relative path, so ingesting from a relative
    # directory would otherwise crash here rather than in the caller.
    path = path.resolve()
    meta: dict = {}
    for key, value in raw.items():
        if value is None:
            continue
        meta[key] = value if isinstance(value, (str, int, float, bool)) else str(value)
    meta.setdefault("document_id", path.stem.upper())
    meta.setdefault("title", path.stem.replace("-", " ").replace("_", " ").title())
    meta.setdefault("doc_type", path.parent.name)
    meta.setdefault("effective_date", "")
    meta.setdefault("source_url", path.as_uri())
    meta["filename"] = path.name
    meta["relpath"] = str(path)
    return meta


def load_markdown(path: Path) -> LoadedDoc:
    raw = path.read_text(encoding="utf-8")
    meta: dict = {}
    match = _FRONT_MATTER.match(raw)
    if match:
        meta = yaml.safe_load(match.group(1)) or {}
        raw = raw[match.end():]
    return LoadedDoc(text=raw.strip(), meta=_normalise_meta(meta, path))


def load_html(path: Path) -> LoadedDoc:
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "html.parser")

    meta: dict = {}
    for tag in soup.find_all("meta"):
        name, content = tag.get("name"), tag.get("content")
        if name and content:
            meta[name] = content
    if soup.title and soup.title.string:
        meta.setdefault("title", soup.title.string.strip())

    # Strip chrome that would otherwise become chunk text and pollute retrieval.
    for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
        tag.decompose()

    root = soup.find("main") or soup.body or soup
    text = _html_to_text(root)
    return LoadedDoc(text=text, meta=_normalise_meta(meta, path))


def _html_to_text(root) -> str:
    """Keep headings and tables legible instead of collapsing to one blob."""
    parts: list[str] = []
    for el in root.find_all(["h1", "h2", "h3", "h4", "p", "li", "table", "blockquote"]):
        if el.find_parent("table") is not None and el.name != "table":
            continue
        if el.name.startswith("h"):
            level = int(el.name[1])
            parts.append(f"\n{'#' * level} {el.get_text(' ', strip=True)}\n")
        elif el.name == "table":
            parts.append(_table_to_text(el))
        elif el.name == "li":
            parts.append(f"- {el.get_text(' ', strip=True)}")
        else:
            parts.append(el.get_text(" ", strip=True))
    text = "\n".join(p for p in parts if p.strip())
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _table_to_text(table) -> str:
    """Markdown-style rows keep a cell tied to its column name inside one chunk."""
    rows = []
    for tr in table.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["th", "td"])]
        if cells:
            rows.append(" | ".join(cells))
    return "\n" + "\n".join(rows) + "\n" if rows else ""


_PDF_NOISE = re.compile(r"^\s*(Page\s+\d+\s+of\s+\d+|\d+\s*/\s*\d+)\s*$", re.I)

# Structural keywords, not one document family's. A policy uses PART, a contract ARTICLE,
# an SDK reference CHAPTER, a handbook SECTION — all the same job. Requires the keyword in
# caps followed by a letter/number label, which rejects mid-sentence prose like
# "Part C of this document" while catching "PART - A", "SECTION 4:", "ARTICLE II".
_STRUCTURAL_WORDS = (
    "PART", "SECTION", "CHAPTER", "ARTICLE", "ANNEXURE", "ANNEX", "APPENDIX",
    "SCHEDULE", "CLAUSE", "EXHIBIT", "TITLE", "DIVISION", "MODULE",
)
_STRUCTURAL_HEADING = re.compile(
    r"^(?:" + "|".join(_STRUCTURAL_WORDS) + r")\s*[-–—:]?\s*"
    r"(?:[IVXLC]+|[A-Z]|\d{1,3})\b",
)

# A short all-caps line on its own — PREAMBLE, DEFINITIONS, SCOPE, LIMITATION OF LIABILITY.
_CAPS_HEADING = re.compile(r"^[A-Z][A-Z &,\-'/()0-9.]{5,60}$")

# Numbered or lettered clauses: "3. Annuity means…", "4.2 Termination", "(a) Coverage".
_NUMBERED_HEADING = re.compile(r"^(\d{1,2}(?:\.\d{1,2})*)\.?\s+([A-Z].{2,})$")


def _promote_plaintext_headings(page_text: str) -> str:
    """Turn a PDF's *visual* structure into Markdown headings.

    A real policy PDF has no ``#`` markers — its structure is font size, capitals, and
    clause numbering. Without this the whole document is one undifferentiated section, and
    two things silently degrade:

    * every chunk's contextual header collapses to the same document title, so the trick
      that makes chunks findable stops differentiating anything;
    * citations can only name the document, never the clause inside it.

    Promoting these lines lets the existing ``_sections`` machinery work unchanged.
    Deliberately conservative — a false heading fragments a clause, which is worse than a
    missed one.
    """
    out: list[str] = []
    for line in page_text.split("\n"):
        stripped = line.strip()

        # Running headers/footers match every query weakly and pollute retrieval.
        if not stripped or _PDF_NOISE.match(stripped):
            out.append("")
            continue

        if len(stripped) < 80:
            # "PART - A", "SECTION 4: SCOPE", "ARTICLE II", "ANNEXURE 1".
            if _STRUCTURAL_HEADING.match(stripped):
                out.append(f"\n## {stripped}\n")
                continue
            # Standalone all-caps markers: PREAMBLE, DEFINITIONS, SCHEDULE.
            if _CAPS_HEADING.match(stripped):
                out.append(f"\n## {stripped}\n")
                continue

        # Numbered clauses and definitions: "3. Annuity means ...". Kept at level 3 so they
        # nest under the PART they belong to, and truncated so a citation stays readable.
        numbered = _NUMBERED_HEADING.match(stripped)
        if numbered:
            label = numbered.group(2).strip()
            short = label if len(label) <= 60 else label[:57].rstrip() + "..."
            out.append(f"\n### {numbered.group(1)}. {short}\n")
            # The full text stays in the body — the heading is a label, not a replacement.
            out.append(stripped)
            continue

        out.append(line)
    return "\n".join(out)


def load_pdf(path: Path) -> LoadedDoc:
    reader = PdfReader(str(path))

    info = reader.metadata or {}
    meta = {k.lstrip("/").lower(): str(v) for k, v in info.items() if v}
    if "title" in meta and not meta["title"].strip():
        meta.pop("title")

    chunks: list[str] = []
    page_breaks: list[tuple[int, int]] = []
    offset = 0
    for page_no, page in enumerate(reader.pages, start=1):
        raw = (page.extract_text() or "").strip()
        if not raw:
            continue
        # Promote headings BEFORE measuring, or the inserted "##" markers shift every
        # offset and the page number attached to each chunk drifts out of step.
        page_text = _promote_plaintext_headings(raw).strip()
        if not page_text:
            continue
        page_breaks.append((offset, page_no))
        chunks.append(page_text)
        offset += len(page_text) + 2

    doc = LoadedDoc(text="\n\n".join(chunks), meta=_normalise_meta(meta, path))
    doc.page_breaks = page_breaks
    return doc


_LOADERS = {
    ".md": load_markdown,
    ".markdown": load_markdown,
    ".txt": load_markdown,
    ".html": load_html,
    ".htm": load_html,
    ".pdf": load_pdf,
}

SIDECAR_NAME = "metadata.yaml"


def load_sidecar(root: Path) -> dict[str, dict]:
    """Optional ``data/metadata.yaml`` keyed by filename.

    PDFs and scraped HTML rarely carry the fields needed for citation and filtering
    (effective_date, document_id, supersedes). Rather than editing binary sources, the
    corpus can be annotated alongside it. Sidecar values win over format-derived ones.
    """
    path = root / SIDECAR_NAME
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {k: (v or {}) for k, v in data.items()}


def load_path(path: Path, sidecar: dict[str, dict] | None = None) -> LoadedDoc | None:
    loader = _LOADERS.get(path.suffix.lower())
    if loader is None:
        return None
    doc = loader(path)
    if not doc.text.strip():
        return None
    overrides = (sidecar or {}).get(path.name)
    if overrides:
        doc.meta.update(
            {k: (v if isinstance(v, (str, int, float, bool)) else str(v))
             for k, v in overrides.items() if v is not None}
        )
    return doc


def load_corpus(root: Path) -> list[LoadedDoc]:
    """Load every supported file under ``root``, recursively and deterministically."""
    sidecar = load_sidecar(root)
    docs: list[LoadedDoc] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.name == SIDECAR_NAME:
            continue
        doc = load_path(path, sidecar)
        if doc is not None:
            docs.append(doc)
    return docs
