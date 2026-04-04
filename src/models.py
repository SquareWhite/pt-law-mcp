from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel


class Law(BaseModel):
    id: str
    full_name: str
    short_name: str
    diploma_type: str
    diploma_number: str
    eli_uri: str | None = None


class Article(BaseModel):
    id: str
    law_id: str
    number: str
    title: str | None = None
    text: str
    chapter: str | None = None
    section: str | None = None


class Reference(BaseModel):
    source_id: str
    target_id: str
    context: str
    ref_type: Literal["remissão", "exceção", "aplicação", "unknown"] = "remissão"
    target_fragment: str | None = None


class AmbiguousReference(BaseModel):
    source_id: str
    raw_text: str
    reason: str
    candidates: list[str] = []


# ── MCP tool response models ──────────────────────────────────────────────────


class ArticleData(BaseModel):
    """Article content returned by read_article and search_articles."""

    id: str
    law_id: str
    number: str
    title: str | None = None
    summary_hint: str | None = None
    text: str | None = None
    chapter: str | None = None
    section: str | None = None


class ReferenceEntry(BaseModel):
    """A referenced article with its relationship context (flat mode)."""

    article: ArticleData
    context: str | None = None
    ref_type: str | None = None
    target_fragment: str | None = None


class ScoredReferenceEntry(BaseModel):
    """A referenced article scored by semantic relevance (tiered mode)."""

    relevance: float
    relevance_norm: float
    referenced_from: str
    context: str | None = None
    ref_type: str | None = None
    # critical / supporting: full article included
    article: ArticleData | None = None
    # peripheral: article-level fields inlined
    id: str | None = None
    title: str | None = None
    summary_hint: str | None = None


class ReadArticleResult(BaseModel):
    """Response from read_article. References are either flat (depth-keyed) or tiered."""

    article: ArticleData
    # flat mode (no query)
    references: dict[int, list[ReferenceEntry]] | None = None
    # tiered mode (query provided)
    critical_references: list[ScoredReferenceEntry] | None = None
    supporting_references: list[ScoredReferenceEntry] | None = None
    peripheral_references: list[ScoredReferenceEntry] | None = None
    metadata: dict[str, Any]
    incoming_references: list[dict[str, Any]] | None = None


class SearchResultItem(BaseModel):
    id: str
    law_id: str
    number: str
    title: str | None = None
    summary_hint: str | None = None
    snippet: str = ""
    chapter: str | None = None
    ref_count: int = 0
    score: float


class SearchArticlesResult(BaseModel):
    results: list[SearchResultItem]


class ArticleEntry(BaseModel):
    id: str
    number: str
    title: str | None = None


class SectionEntry(BaseModel):
    title: str
    articles: list[ArticleEntry]


class ChapterEntry(BaseModel):
    title: str
    articles: list[ArticleEntry] = []
    sections: list[SectionEntry] = []


class LawStructureResult(BaseModel):
    law_id: str
    structure: list[ChapterEntry]


class GraphNode(BaseModel):
    id: str
    title: str | None = None
    law_id: str


class GraphEdge(BaseModel):
    source: str
    target: str
    ref_type: str | None = None


class RefGraphResult(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]
