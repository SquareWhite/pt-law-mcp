from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Any, Generator

import numpy as np
from neo4j import Session

from src.db.connection import get_driver, get_session
from src.db.schema import apply_schema
from src.models import (
    ArticleData,
    ReadArticleResult,
    ReferenceEntry,
    ScoredReferenceEntry,
)

TOKEN_BUDGET = int(os.getenv("TOKEN_BUDGET", "8000"))
CRITICAL_THRESHOLD = float(os.getenv("CRITICAL_THRESHOLD", "0.5"))
SUPPORTING_THRESHOLD = float(os.getenv("SUPPORTING_THRESHOLD", "0.3"))

_embedder = None
_schema_applied = False


def get_embedder():
    global _embedder
    if _embedder is None:
        from src.embeddings import EmbeddingService

        _embedder = EmbeddingService()
    return _embedder


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Session context manager that also ensures schema is initialised on first call."""
    global _schema_applied
    if not _schema_applied:
        apply_schema(get_driver())
        _schema_applied = True
    with get_session() as session:
        yield session


def word_count(text: str | None) -> int:
    if not text:
        return 0
    return len(text.split())


def cosine_similarity(a: list[float], b: list[float]) -> float:
    va = np.array(a, dtype=np.float32)
    vb = np.array(b, dtype=np.float32)
    norm_a = np.linalg.norm(va)
    norm_b = np.linalg.norm(vb)
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(np.dot(va, vb) / (norm_a * norm_b))


def first_paragraph(text: str | None) -> str:
    if not text:
        return ""
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    return paragraphs[0] if paragraphs else text[:300]


def article_data(art: dict) -> ArticleData:
    return ArticleData(
        id=art["id"],
        law_id=art.get("law_id", ""),
        number=art.get("number", ""),
        title=art.get("title"),
        summary_hint=art.get("summary_hint"),
        text=art.get("text"),
        chapter=art.get("chapter"),
    )


def build_tiered_response(
    root: dict,
    raw_refs: list[dict],
    query: str,
    article_id: str,
    incoming: list[dict[str, Any]] | None,
) -> ReadArticleResult:
    embedder = get_embedder()
    query_embedding = embedder.embed_query(query)

    visited: set[str] = {root["id"]}
    cycle_warnings: list[str] = []
    scored: list[tuple[float, dict, dict]] = []  # (raw_sim, ref, art)

    for ref in raw_refs:
        art = ref.get("article")
        if not art:
            continue
        ref_id = art.get("id")
        if not ref_id:
            continue
        if ref_id in visited:
            cycle_warnings.append(f"{article_id} → {ref_id} (cycle)")
            continue
        visited.add(ref_id)

        art_embedding = art.get("embedding")
        sim = cosine_similarity(query_embedding, art_embedding) if art_embedding else 0.0
        scored.append((sim, ref, art))

    # Normalize scores to [0, 1] relative to this batch.
    # Cosine sims for same-domain legal text cluster tightly (e.g. 0.78–0.87),
    # so absolute thresholds are meaningless — only relative rank matters.
    if scored:
        raw_sims = [s for s, _, _ in scored]
        sim_min = min(raw_sims)
        sim_max = max(raw_sims)
        sim_range = sim_max - sim_min
    else:
        sim_min = sim_max = sim_range = 0.0

    critical: list[ScoredReferenceEntry] = []
    supporting: list[ScoredReferenceEntry] = []
    peripheral: list[ScoredReferenceEntry] = []

    for raw_sim, ref, art in scored:
        norm = (raw_sim - sim_min) / sim_range if sim_range > 1e-6 else 1.0

        base = dict(
            relevance=round(raw_sim, 4),
            relevance_norm=round(norm, 4),
            referenced_from=article_id,
            context=ref.get("context"),
            ref_type=ref.get("ref_type"),
        )

        if norm >= CRITICAL_THRESHOLD:
            critical.append(ScoredReferenceEntry(**base, article=article_data(art)))
        elif norm >= SUPPORTING_THRESHOLD:
            supporting.append(
                ScoredReferenceEntry(
                    **base,
                    article=ArticleData(
                        id=art["id"],
                        law_id=art.get("law_id", ""),
                        number=art.get("number", ""),
                        title=art.get("title"),
                        summary_hint=art.get("summary_hint"),
                        text=first_paragraph(art.get("text")),
                        chapter=art.get("chapter"),
                    ),
                )
            )
        else:
            peripheral.append(
                ScoredReferenceEntry(
                    **base,
                    id=art.get("id"),
                    title=art.get("title"),
                    summary_hint=art.get("summary_hint"),
                )
            )

    return ReadArticleResult(
        article=article_data(root),
        critical_references=sorted(critical, key=lambda x: x.relevance, reverse=True),
        supporting_references=sorted(supporting, key=lambda x: x.relevance, reverse=True),
        peripheral_references=sorted(peripheral, key=lambda x: x.relevance, reverse=True),
        metadata={
            "total_articles_in_graph": len(visited),
            "articles_with_full_text": 1 + len(critical),
            "query_used": query,
            "cycle_warnings": cycle_warnings,
        },
        incoming_references=incoming,
    )


def build_law_structure(rows: list[dict]) -> list:
    """Group flat article rows into a nested chapter → section → articles structure."""
    from src.models import ArticleEntry, ChapterEntry, SectionEntry

    chapters_map: dict[str, dict] = {}
    for row in rows:
        chapter = row.get("chapter") or "Sem capítulo"
        section = row.get("section") or ""

        if chapter not in chapters_map:
            chapters_map[chapter] = {"title": chapter, "sections": {}, "articles": []}

        entry = ArticleEntry(id=row["id"], number=row["number"], title=row["title"])
        if section:
            chapters_map[chapter]["sections"].setdefault(
                section, {"title": section, "articles": []}
            )["articles"].append(entry)
        else:
            chapters_map[chapter]["articles"].append(entry)

    return [
        ChapterEntry(
            title=ch["title"],
            articles=ch["articles"],
            sections=[
                SectionEntry(title=s["title"], articles=s["articles"])
                for s in ch["sections"].values()
            ],
        )
        for ch in chapters_map.values()
    ]


def merge_search_results(
    ft_results: list[dict],
    vec_results: list[dict],
) -> list[dict]:
    """Merge fulltext and vector search results into a single ranked list.

    Combines scores as 0.4 * normalised_fulltext + 0.6 * vector_score,
    sorted descending by combined score.
    """
    max_ft = max((r.get("score", 0) for r in ft_results), default=1.0) or 1.0
    ft_by_id = {r["id"]: {**r, "ft_norm": (r.get("score", 0) or 0) / max_ft} for r in ft_results}
    vec_by_id = {r["id"]: r for r in vec_results}

    merged = []
    for aid in set(ft_by_id) | set(vec_by_id):
        ft = ft_by_id.get(aid, {})
        vec = vec_by_id.get(aid, {})
        combined = 0.4 * ft.get("ft_norm", 0.0) + 0.6 * vec.get("vector_score", 0.0)
        merged.append({**(ft if ft else vec), "combined_score": combined})

    merged.sort(key=lambda x: x["combined_score"], reverse=True)
    return merged


def build_flat_response(
    root: dict,
    raw_refs: list[dict],
    article_id: str,
    incoming: list[dict[str, Any]] | None,
) -> ReadArticleResult:
    visited: set[str] = {root["id"]}
    cycle_warnings: list[str] = []
    total_words = word_count(root.get("text"))
    truncated = False

    expanded_by_depth: dict[int, list[ReferenceEntry]] = {}
    for ref in sorted(raw_refs, key=lambda r: (r["depth"], -(r.get("out_ref_count") or 0))):
        art = ref.get("article")
        if not art:
            continue
        ref_id = art.get("id")
        if not ref_id:
            continue

        d = ref["depth"]

        if ref_id in visited:
            cycle_warnings.append(f"{article_id} → {ref_id} (cycle)")
            continue

        words = word_count(art.get("text"))
        if total_words + words > TOKEN_BUDGET:
            truncated = True
            continue

        visited.add(ref_id)
        total_words += words
        expanded_by_depth.setdefault(d, []).append(
            ReferenceEntry(
                article=article_data(art),
                context=ref.get("context"),
                ref_type=ref.get("ref_type"),
                target_fragment=ref.get("target_fragment"),
            )
        )

    return ReadArticleResult(
        article=article_data(root),
        references=expanded_by_depth,
        metadata={
            "total_articles_returned": len(visited),
            "cycle_warnings": cycle_warnings,
            "truncated": truncated,
        },
        incoming_references=incoming,
    )
