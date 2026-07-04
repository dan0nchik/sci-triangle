"""A5: chunking (~1000 tokens, overlap 100) along paragraph/heading
boundaries, language detection, and junk filtering (running headers/footers,
pure tables-of-contents, advertising pages).
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from . import config


@dataclass
class Chunk:
    text: str
    seq: int
    page_from: int
    page_to: int
    lang: str
    n_tokens: int
    section_title: str | None


_cyr = re.compile(r"[а-яёА-ЯЁ]")
_lat = re.compile(r"[a-zA-Z]")
# dot-leader TOC line: "... Глава 3 ......... 45"
_toc_line = re.compile(r".{3,}[.…]{4,}\s*\d+\s*$")
_page_num_only = re.compile(r"^\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*$")
_heading_re = re.compile(
    r"^\s*(?:\d+(?:\.\d+){0,3}\.?\s+\S|[A-ZА-ЯЁ][^\n]{0,80})$"
)


def detect_lang(text: str) -> str:
    cyr = len(_cyr.findall(text))
    lat = len(_lat.findall(text))
    total = cyr + lat
    if total < 20:
        return "ru"  # default for this corpus
    r = cyr / total
    if r >= 0.7:
        return "ru"
    if r <= 0.15:
        return "en"
    return "mixed"


def _estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / config.CHARS_PER_TOKEN))


def _strip_running_headers(pages: list[tuple[int, str]]) -> list[tuple[int, str]]:
    """Remove short lines that repeat across many pages (running heads/feet)
    and bare page numbers."""
    if len(pages) < 4:
        cleaned = []
        for pno, txt in pages:
            lines = [ln for ln in txt.splitlines() if not _page_num_only.match(ln)]
            cleaned.append((pno, "\n".join(lines)))
        return cleaned

    line_pages: Counter[str] = Counter()
    for _, txt in pages:
        seen = set()
        for ln in txt.splitlines():
            s = ln.strip()
            if 3 <= len(s) <= 80:
                seen.add(s)
        for s in seen:
            line_pages[s] += 1

    threshold = max(3, int(0.4 * len(pages)))
    repeated = {s for s, c in line_pages.items() if c >= threshold}

    cleaned = []
    for pno, txt in pages:
        out_lines = []
        for ln in txt.splitlines():
            s = ln.strip()
            if s in repeated:
                continue
            if _page_num_only.match(ln):
                continue
            out_lines.append(ln)
        cleaned.append((pno, "\n".join(out_lines)))
    return cleaned


def _is_toc_or_ad(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return True
    toc = sum(1 for ln in lines if _toc_line.search(ln))
    if toc >= 5 and toc / len(lines) > 0.5:
        return True
    return False


def _looks_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90:
        return False
    if _toc_line.search(s):
        return False
    # numbered heading e.g. "3.2 Скорость циркуляции"
    if re.match(r"^\d+(?:\.\d+){0,3}\.?\s+\S", s):
        return True
    # short all-caps-ish title
    letters = _cyr.findall(s) + _lat.findall(s)
    if letters and not s.endswith((".", ",", ";", ":")) and len(s.split()) <= 10:
        upper = sum(1 for ch in s if ch.isupper())
        if upper / max(1, len(letters)) > 0.5:
            return True
    return False


_sentence_end = re.compile(r"(?<=[.!?;])\s+")


def _split_oversized(para: str, limit: int = config.CHUNK_CHARS) -> list[str]:
    """Split a unit larger than the chunk budget on newlines (tables) or
    sentence boundaries, falling back to a hard cut."""
    if len(para) <= limit:
        return [para]
    out: list[str] = []
    lines = para.splitlines() if "\n" in para else _sentence_end.split(para)
    cur: list[str] = []
    cur_len = 0
    joiner = "\n" if "\n" in para else " "
    for piece in lines:
        if cur and cur_len + len(piece) > limit:
            out.append(joiner.join(cur))
            cur, cur_len = [], 0
        # hard cut pathological single lines/sentences
        while len(piece) > limit:
            out.append(piece[:limit])
            piece = piece[limit:]
        cur.append(piece)
        cur_len += len(piece) + 1
    if cur:
        out.append(joiner.join(cur))
    return [p for p in out if p.strip()]


def chunk_document(pages: list[tuple[int, str]]) -> list[Chunk]:
    pages = _strip_running_headers(pages)

    # build paragraph units carrying their page number + current heading
    units: list[tuple[str, int, str | None]] = []  # (text, page, section_title)
    current_heading: str | None = None
    for pno, txt in pages:
        # split into paragraphs on blank lines; also treat single newlines as
        # soft breaks by first collapsing intra-paragraph line wraps.
        blocks = re.split(r"\n\s*\n", txt)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            first_line = block.splitlines()[0]
            if _looks_heading(first_line):
                current_heading = first_line.strip()
            if "\t" in block:
                para = block  # tabular block (xls sheet): keep line structure
            else:
                para = re.sub(r"[ \t]*\n[ \t]*", " ", block).strip()
                para = re.sub(r"[ \t]{2,}", " ", para)
            if para:
                for piece in _split_oversized(para):
                    units.append((piece, pno, current_heading))

    chunks: list[Chunk] = []
    seq = 0
    buf: list[str] = []
    buf_len = 0
    buf_pages: list[int] = []
    buf_title: str | None = None

    def flush():
        nonlocal seq, buf, buf_len, buf_pages, buf_title
        if not buf:
            return
        text = "\n\n".join(buf).strip()
        if len(text) >= config.MIN_CHUNK_CHARS and not _is_toc_or_ad(text):
            # HARD CAP: never emit a chunk above MAX_CHUNK_CHARS (~1200 tok);
            # split by sentences/lines with a small overlap between pieces.
            pieces = ([text] if len(text) <= config.MAX_CHUNK_CHARS
                      else _split_oversized(text, config.MAX_CHUNK_CHARS
                                            - config.OVERLAP_CHARS))
            prev_tail = ""
            for piece in pieces:
                if prev_tail:
                    piece = prev_tail + " " + piece
                prev_tail = piece[-config.OVERLAP_CHARS:] if len(pieces) > 1 else ""
                if len(piece) < config.MIN_CHUNK_CHARS:
                    continue
                chunks.append(Chunk(
                    text=piece, seq=seq,
                    page_from=min(buf_pages), page_to=max(buf_pages),
                    lang=detect_lang(piece), n_tokens=_estimate_tokens(piece),
                    section_title=buf_title,
                ))
                seq += 1
        buf, buf_len, buf_pages, buf_title = [], 0, [], None

    for para, pno, title in units:
        if buf_title is None:
            buf_title = title
        if buf and buf_len + len(para) > config.CHUNK_CHARS:
            flush()
            # overlap: carry tail of previous chunk
            if chunks:
                tail = chunks[-1].text[-config.OVERLAP_CHARS:]
                buf = [tail]
                buf_len = len(tail)
                buf_pages = [pno]
                buf_title = title
        buf.append(para)
        buf_len += len(para) + 2
        buf_pages.append(pno)
    flush()
    return chunks
