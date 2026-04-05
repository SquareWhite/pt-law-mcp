from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

# Fraction of page height to strip at top/bottom (catches running headers & page numbers)
_MARGIN_FRACTION = 0.10

# Single-token page numbers
_PAGE_NUM_RE = re.compile(r"^\d+$")


def _clean_block(raw: str) -> str:
    """Collapse soft-wrapped lines in a block into a single flowing string."""
    return " ".join(line.strip() for line in raw.splitlines() if line.strip())


def read_pdf(path: Path) -> list[tuple[str, str]]:
    """Return a single (title, html_content) tuple for the whole document.

    Strips running headers/footers by ignoring blocks that fall within the top
    or bottom 10 % of each page.  Remaining blocks are wrapped in <p> tags and
    returned as a single pseudo-chapter so the existing article_splitter can
    process them unchanged.
    """
    try:
        import fitz  # pymupdf
    except ImportError as exc:
        raise ImportError(
            "pymupdf is required for PDF ingestion — add it to pyproject.toml"
        ) from exc

    try:
        doc = fitz.open(str(path))
    except Exception as exc:
        raise ValueError(f"Failed to open PDF at {path}: {exc}") from exc

    html_parts = ["<html><body>"]

    for page in doc:
        page_height = page.rect.height
        top_cutoff = _MARGIN_FRACTION * page_height
        bottom_cutoff = (1.0 - _MARGIN_FRACTION) * page_height

        # blocks: (x0, y0, x1, y1, text, block_no, block_type)
        for block in page.get_text("blocks"):
            if block[6] != 0:  # skip image blocks
                continue
            y0, y1 = block[1], block[3]
            if y1 <= top_cutoff or y0 >= bottom_cutoff:
                continue
            text = _clean_block(block[4])
            if not text or _PAGE_NUM_RE.match(text):
                continue
            html_parts.append(f"<p>{text}</p>")

    html_parts.append("</body></html>")

    return [(path.stem, "\n".join(html_parts))]
