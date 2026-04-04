from __future__ import annotations

import logging
import re
import warnings

from bs4 import BeautifulSoup, Tag, XMLParsedAsHTMLWarning

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)

from src.models import Article

logger = logging.getLogger(__name__)

# Matches: "Artigo 22.º" or "Artigo 88.º-A"
_ARTICLE_RE = re.compile(r"Artigo\s+(\d+)\.?º(?:-([A-Z]))?", re.UNICODE)

# Headings that define structural context
_HEADING_RE = re.compile(
    r"^(Parte|Título|Capítulo|Secção)\s*[IVX\d]", re.IGNORECASE | re.UNICODE
)

_REVOKED_RE = re.compile(r"\(Revogado\)", re.IGNORECASE)

# Block-level tags whose full text we want (including inline children like <br>, <span>)
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td", "th"}


def _extract_text(soup: BeautifulSoup) -> list[tuple[str, str]]:
    """Return (tag_name, text) for every block-level element in document order.

    Using get_text(' ') on the element flattens inline children (br, span, a)
    into a single string, which is exactly what we want: article headers like
    <h4>Artigo 1.º<br/>Base do imposto</h4> become "Artigo 1.º Base do imposto".
    We only skip elements that are themselves nested inside another block tag
    (e.g. a <p> inside a <td>) to avoid double-counting.
    """
    pairs: list[tuple[str, str]] = []
    for el in soup.find_all(_BLOCK_TAGS):
        if not isinstance(el, Tag):
            continue
        if el.find_parent(["table", "nav"]):
            continue
        # Skip if a closer block-level ancestor already covers this text
        parent = el.parent
        if parent and parent.name in _BLOCK_TAGS:
            continue
        text = el.get_text(" ", strip=True)
        # Collapse internal whitespace
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            pairs.append((el.name, text))
    return pairs


def split_articles(
    chapters: list[tuple[str, str]], law_id: str
) -> list[Article]:
    articles: list[Article] = []

    current_chapter: str | None = None
    current_section: str | None = None

    # Buffer for building each article
    current_number: str | None = None
    current_title: str | None = None
    current_lines: list[str] = []
    expect_title = False

    def flush() -> None:
        nonlocal current_number, current_title, current_lines, expect_title
        if current_number is None:
            return
        text = "\n".join(current_lines).strip()
        article_id = f"{law_id}:art:{current_number}"
        articles.append(
            Article(
                id=article_id,
                law_id=law_id,
                number=current_number,
                title=current_title,
                text=text,
                chapter=current_chapter,
                section=current_section,
            )
        )
        current_number = None
        current_title = None
        current_lines = []
        expect_title = False

    for _chapter_title, html in chapters:
        try:
            soup = BeautifulSoup(html, "lxml")
            pairs = _extract_text(soup)
        except Exception as exc:
            logger.warning("Skipping malformed chapter %r: %s", _chapter_title, exc)
            continue

        for _tag, text in pairs:
            # Structural heading?
            if _HEADING_RE.match(text):
                flush()
                lower = text.lower()
                if lower.startswith("secção"):
                    current_section = text
                else:
                    current_chapter = text
                    current_section = None
                continue

            # Article boundary?
            m = _ARTICLE_RE.match(text)
            if m:
                flush()
                number = m.group(1)
                suffix = m.group(2)
                current_number = f"{number}-{suffix}" if suffix else number

                # Title may be inline in the same element after the article header
                inline_title = text[m.end():].strip()
                if inline_title and not _REVOKED_RE.search(inline_title):
                    current_title = inline_title
                    expect_title = False
                elif _REVOKED_RE.search(inline_title):
                    current_lines.append(inline_title)
                    expect_title = False
                else:
                    expect_title = True
                continue

            if current_number is None:
                continue

            # If we just saw an article header with no inline title,
            # next non-empty line is the title
            if expect_title:
                if not _REVOKED_RE.search(text):
                    current_title = text
                else:
                    current_lines.append(text)
                expect_title = False
                continue

            current_lines.append(text)

    flush()
    return articles
