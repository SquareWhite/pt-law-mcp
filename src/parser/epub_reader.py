from __future__ import annotations

import logging
import re
from pathlib import Path

import warnings

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

logger = logging.getLogger(__name__)


_SKIP_TITLES = re.compile(
    r"(cover|copyright|toc|table.of.contents|índice|capa|contracapa|ficha.técnica"
    r"|decreto.lei|decreto.legislativo|lei\s+n|portaria\s+n)",
    re.IGNORECASE,
)
_MIN_TEXT_LENGTH = 200


def _is_content_item(item: ebooklib.epub.EpubItem) -> bool:
    if item.get_type() != ebooklib.ITEM_DOCUMENT:
        return False
    content = item.get_content().decode("utf-8", errors="replace")
    soup = BeautifulSoup(content, "lxml")
    title = soup.title.string if soup.title else ""
    h1 = soup.find("h1")
    heading = h1.get_text(strip=True) if h1 else ""
    if _SKIP_TITLES.search(title or heading):
        return False
    text = soup.get_text()
    if len(text.strip()) < _MIN_TEXT_LENGTH:
        return False
    # Skip pure TOC pages: high link density relative to word count
    links = soup.find_all("a")
    words = len(text.split())
    if words > 0 and len(links) / words > 0.05:
        return False
    return True


def _chapter_title(item: ebooklib.epub.EpubItem, spine_index: int) -> str:
    content = item.get_content().decode("utf-8", errors="replace")
    soup = BeautifulSoup(content, "lxml")
    for tag in ("h1", "h2", "h3", "title"):
        el = soup.find(tag)
        if el and el.get_text(strip=True):
            return el.get_text(strip=True)
    return f"chapter_{spine_index}"


def read_epub(path: Path) -> list[tuple[str, str]]:
    """Return (chapter_title, html_content) tuples for each content document."""
    try:
        book = epub.read_epub(str(path))
    except Exception as exc:
        raise ValueError(f"Failed to read EPUB at {path}: {exc}") from exc

    spine_ids = {item_id for item_id, _ in book.spine}

    results: list[tuple[str, str]] = []
    for index, item in enumerate(book.get_items()):
        if item.id not in spine_ids:
            continue
        if not _is_content_item(item):
            continue
        html = item.get_content().decode("utf-8", errors="replace")
        title = _chapter_title(item, index)
        results.append((title, html))

    return results
