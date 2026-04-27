"""
v3.9.0 — Structure-aware + semantic chunking.

Pipeline:
  1. Structure-aware pre-split: the text is first cut along its own hierarchy
     (Markdown headings, numbered articles like "1.", "1.1", "Article 3", etc.).
     Inside each block we keep sentences grouped by their structural parent.
  2. Semantic split: sentences inside each block are embedded with bge-m3, and
     a new chunk boundary is placed whenever the cosine distance between two
     consecutive sentences jumps above a percentile threshold — i.e. where the
     topic actually changes. Chunks grow naturally between MIN and MAX tokens.
  3. Overlap of 1 sentence between adjacent chunks to preserve coreferences.

All thresholds are configurable via env vars; defaults are robust for French
payroll / HR specs.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
from langchain_core.documents import Document

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables (override via env)
# ---------------------------------------------------------------------------

CHUNKER_VERSION = "v2"  # bumped whenever chunking behavior changes

# Target sizes, measured in characters (rough 1 token ≈ 4 chars for French).
CHUNK_MIN_CHARS = int(os.getenv("CHUNK_MIN_CHARS", "400"))   # ≈ 100 tokens
CHUNK_TARGET_CHARS = int(os.getenv("CHUNK_TARGET_CHARS", "2400"))  # ≈ 600 tokens
CHUNK_MAX_CHARS = int(os.getenv("CHUNK_MAX_CHARS", "3600"))  # ≈ 900 tokens

# Percentile of sentence-to-sentence cosine distances above which we cut.
# 90 means "cut on the 10% biggest topic shifts". Lower ⇒ more cuts ⇒ smaller chunks.
SEMANTIC_BREAK_PERCENTILE = int(os.getenv("SEMANTIC_BREAK_PERCENTILE", "90"))

# How many sentences to embed together (window). 1 = each sentence alone.
# 2-3 gives smoother distance signal on short sentences.
SEMANTIC_SENTENCE_WINDOW = int(os.getenv("SEMANTIC_SENTENCE_WINDOW", "2"))

# Sentence overlap between consecutive chunks (to preserve coreferences).
CHUNK_SENTENCE_OVERLAP = int(os.getenv("CHUNK_SENTENCE_OVERLAP", "1"))

# Absolute minimum sentences per chunk (avoid degenerate 1-sentence chunks).
MIN_SENTENCES_PER_CHUNK = int(os.getenv("MIN_SENTENCES_PER_CHUNK", "2"))

# Safety: if a document produces more than this many sentences, fall back to
# the cheap size-based splitter (CPU embedding would take too long).
MAX_SENTENCES_BEFORE_FALLBACK = int(os.getenv("MAX_SENTENCES_BEFORE_FALLBACK", "1500"))


# ---------------------------------------------------------------------------
# Structure-aware pre-split
# ---------------------------------------------------------------------------

# Matches typical headings in French specifications:
#   Markdown: "# Title", "## Section"
#   Numbered: "1. ", "1.1 ", "1.1.1 ", "A. ", "I. "
#   Keyword:  "Article 3", "Section II", "Chapitre 4", "Annexe A"
_HEADING_RE = re.compile(
    r"^(?:"
    r"(?P<md>#{1,6}\s+.+)"                                 # markdown heading
    r"|(?P<num>\d+(?:\.\d+){0,4}\.?\s+[A-ZÀ-ÖØ-Þ][^\n]{0,200})"  # 1.2.3 Title
    r"|(?P<kw>(?:Article|Section|Chapitre|Chapter|Annexe|Partie|Titre)\s+[IVXLC0-9]+[^\n]{0,200})"
    r")\s*$",
    re.MULTILINE,
)


@dataclass
class StructuralBlock:
    """A block of text sharing the same structural parent (heading path)."""

    heading_path: list[str] = field(default_factory=list)  # e.g. ["Article 3", "3.1 Rémunération"]
    text: str = ""

    @property
    def heading_str(self) -> str:
        return " / ".join(self.heading_path) if self.heading_path else ""


def structure_split(text: str) -> list[StructuralBlock]:
    """Split text into blocks along detected headings, keeping parent path.

    Returns at least one block (the whole text if no headings found).
    """
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [StructuralBlock(heading_path=[], text=text.strip())]

    blocks: list[StructuralBlock] = []

    # Preamble before the first heading
    first = matches[0]
    preamble = text[: first.start()].strip()
    if preamble:
        blocks.append(StructuralBlock(heading_path=[], text=preamble))

    # Track heading hierarchy via numbering depth (when available)
    path: list[tuple[int, str]] = []  # (depth, heading_line)

    def _depth_of(heading_line: str) -> int:
        h = heading_line.strip()
        # Markdown: count leading '#'
        md = re.match(r"^(#{1,6})\s", h)
        if md:
            return len(md.group(1))
        # Numbered: count dots
        num = re.match(r"^(\d+(?:\.\d+){0,4})", h)
        if num:
            return num.group(1).count(".") + 1
        # Keyword headings are treated as depth 1
        return 1

    for i, m in enumerate(matches):
        heading = m.group(0).strip()
        depth = _depth_of(heading)
        # Pop deeper-or-equal ancestors
        while path and path[-1][0] >= depth:
            path.pop()
        path.append((depth, heading))

        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        if not body:
            continue
        blocks.append(
            StructuralBlock(
                heading_path=[h for _, h in path],
                text=body,
            )
        )
    return blocks


# ---------------------------------------------------------------------------
# Sentence splitting (French-aware)
# ---------------------------------------------------------------------------

# Conservative: break on ".!?" or newline runs, but keep list items together.
_SENTENCE_RE = re.compile(
    r"(?<=[\.\!\?])\s+(?=[A-ZÀ-ÖØ-Þ0-9])"  # end of sentence + start of next
    r"|\n{2,}"                               # paragraph break
)


def split_sentences(text: str) -> list[str]:
    text = text.strip()
    if not text:
        return []
    # Protect common abbreviations that shouldn't split (e.g. "M.", "Mme.", "art.")
    protected = re.sub(
        r"\b(M|Mme|Mlle|Dr|Pr|art|Art|n°|No|Cf|cf|ex|Ex|p|pp|vs|etc|Etc)\.\s",
        r"\1§ ", text,
    )
    parts = _SENTENCE_RE.split(protected)
    parts = [p.replace("§ ", ". ").strip() for p in parts if p and p.strip()]
    return parts


# ---------------------------------------------------------------------------
# Semantic chunking
# ---------------------------------------------------------------------------


def _window_embeddings(
    sentences: list[str],
    embed_fn,
    window: int,
) -> np.ndarray:
    """Embed each sentence together with its (window-1) neighbors for a smoother signal."""
    if window <= 1:
        windows = sentences
    else:
        windows = []
        for i in range(len(sentences)):
            lo = max(0, i - (window - 1) // 2)
            hi = min(len(sentences), lo + window)
            windows.append(" ".join(sentences[lo:hi]))
    vecs = np.array(embed_fn(windows), dtype=np.float32)
    # bge-m3 already normalized=True, but re-normalize defensively
    norms = np.linalg.norm(vecs, axis=1, keepdims=True) + 1e-12
    return vecs / norms


def _distances(vecs: np.ndarray) -> np.ndarray:
    """Cosine distance between consecutive rows."""
    if len(vecs) < 2:
        return np.array([], dtype=np.float32)
    sims = np.sum(vecs[:-1] * vecs[1:], axis=1)
    return 1.0 - sims


def _breakpoints(
    distances: np.ndarray,
    sentences: list[str],
    percentile: int,
) -> list[int]:
    """Return indices i such that sentences[:i] and sentences[i:] form a break.

    Uses the percentile of distances as threshold, plus size guards.
    """
    if len(distances) == 0:
        return []
    threshold = float(np.percentile(distances, percentile))
    # We additionally require an absolute minimum spike (filters out flat texts)
    threshold = max(threshold, 0.12)

    breaks: list[int] = []
    cum_chars = 0
    for i, d in enumerate(distances):
        cum_chars += len(sentences[i])
        if cum_chars < CHUNK_MIN_CHARS:
            continue
        if d >= threshold or cum_chars >= CHUNK_TARGET_CHARS:
            # i is the index of the LAST sentence of the current chunk;
            # the next chunk starts at i+1
            breaks.append(i + 1)
            cum_chars = 0
        if cum_chars >= CHUNK_MAX_CHARS:
            # Force cut even on a flat segment
            breaks.append(i + 1)
            cum_chars = 0
    return breaks


def _assemble_chunks(
    sentences: list[str],
    breaks: list[int],
    overlap: int,
) -> list[str]:
    """Assemble final chunk strings from sentence list + break indices."""
    if not sentences:
        return []
    all_breaks = [0, *breaks, len(sentences)]
    all_breaks = sorted(set(all_breaks))
    chunks: list[str] = []
    for a, b in zip(all_breaks[:-1], all_breaks[1:]):
        if b - a < MIN_SENTENCES_PER_CHUNK and len(chunks) > 0:
            # Merge tiny tail into previous chunk
            chunks[-1] = chunks[-1] + " " + " ".join(sentences[a:b])
            continue
        # Add sentence overlap from previous
        start = max(0, a - overlap) if chunks else a
        chunks.append(" ".join(sentences[start:b]).strip())
    return [c for c in chunks if c]


def _size_split(text: str) -> list[str]:
    """Fallback: greedy size-based split on whitespace."""
    words = text.split()
    chunks: list[str] = []
    buf: list[str] = []
    size = 0
    for w in words:
        buf.append(w)
        size += len(w) + 1
        if size >= CHUNK_TARGET_CHARS:
            chunks.append(" ".join(buf))
            buf, size = [], 0
    if buf:
        chunks.append(" ".join(buf))
    return chunks


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def semantic_chunk_documents(
    pages: Iterable[Document],
    embed_fn,
) -> list[Document]:
    """Take LangChain Document pages and return semantically chunked Documents.

    Batches all sentence embeddings for the whole document in a SINGLE call,
    which is 10-50x faster on CPU than one call per structural block.

    Preserves original metadata (page, source) and adds:
      - heading_path: list[str]
      - chunker_version: str

    If the document is very large (> MAX_SENTENCES_BEFORE_FALLBACK sentences),
    falls back to the cheap size-based splitter, still respecting the structural
    hierarchy.
    """
    pages = list(pages)

    # Phase 1: structural split + sentence enumeration for every block
    # Each entry: (base_meta, block, sentences)
    plan: list[tuple[dict, StructuralBlock, list[str]]] = []
    total_sentences = 0
    for page in pages:
        text = page.page_content
        if not text or not text.strip():
            continue
        base_meta = dict(page.metadata or {})
        for block in structure_split(text):
            sents = split_sentences(block.text)
            plan.append((base_meta, block, sents))
            total_sentences += len(sents)

    logger.info(
        "Semantic chunker: %d block(s), %d sentence(s) total.",
        len(plan), total_sentences,
    )

    # Phase 2: fast-path fallback for huge documents — skip embeddings entirely
    if total_sentences > MAX_SENTENCES_BEFORE_FALLBACK:
        logger.warning(
            "Document has %d sentences (> %d). Falling back to size-split with "
            "structural awareness (no per-sentence embeddings) for speed.",
            total_sentences, MAX_SENTENCES_BEFORE_FALLBACK,
        )
        out: list[Document] = []
        for base_meta, block, _sents in plan:
            for chunk_text in _size_split(block.text):
                if not chunk_text.strip():
                    continue
                meta = dict(base_meta)
                meta["heading_path"] = block.heading_path
                meta["heading"] = block.heading_str
                meta["chunker_version"] = CHUNKER_VERSION + "-fastpath"
                out.append(Document(page_content=chunk_text, metadata=meta))
        return out

    # Phase 3: build a single list of windows (sentences in context) and embed
    # them all in ONE batch call — 10-50x faster on CPU than per-block calls.
    all_windows: list[str] = []
    offsets: list[tuple[int, int]] = []  # (start, end) into all_windows per block
    for _base_meta, _block, sents in plan:
        start = len(all_windows)
        if sents:
            if SEMANTIC_SENTENCE_WINDOW <= 1:
                all_windows.extend(sents)
            else:
                for i in range(len(sents)):
                    lo = max(0, i - (SEMANTIC_SENTENCE_WINDOW - 1) // 2)
                    hi = min(len(sents), lo + SEMANTIC_SENTENCE_WINDOW)
                    all_windows.append(" ".join(sents[lo:hi]))
        offsets.append((start, len(all_windows)))

    if all_windows:
        try:
            all_vecs = np.array(embed_fn(all_windows), dtype=np.float32)
            norms = np.linalg.norm(all_vecs, axis=1, keepdims=True) + 1e-12
            all_vecs = all_vecs / norms
        except Exception as exc:
            logger.warning(
                "Batch embedding failed (%s). Falling back to size-split.", exc,
            )
            all_vecs = None
    else:
        all_vecs = None

    # Phase 4: per-block chunk assembly using the pre-computed vectors
    out: list[Document] = []
    for (base_meta, block, sents), (s, e) in zip(plan, offsets):
        if not sents:
            continue
        # Too short: keep whole block as one chunk
        if len(sents) <= 2 or len(block.text) <= CHUNK_TARGET_CHARS // 2:
            chunks = [block.text.strip()]
        elif all_vecs is not None:
            try:
                vecs = all_vecs[s:e]
                distances = _distances(vecs)
                breaks = _breakpoints(distances, sents, SEMANTIC_BREAK_PERCENTILE)
                chunks = _assemble_chunks(sents, breaks, CHUNK_SENTENCE_OVERLAP)
            except Exception as exc:
                logger.warning("Per-block semantic split failed: %s. Size-split.", exc)
                chunks = _size_split(block.text)
        else:
            chunks = _size_split(block.text)

        for chunk_text in chunks:
            if not chunk_text or not chunk_text.strip():
                continue
            meta = dict(base_meta)
            meta["heading_path"] = block.heading_path
            meta["heading"] = block.heading_str
            meta["chunker_version"] = CHUNKER_VERSION
            out.append(Document(page_content=chunk_text, metadata=meta))
    return out
