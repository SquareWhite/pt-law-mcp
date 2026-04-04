from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)

from src.db.repository import (
    fulltext_search,
    get_article_with_refs,
    get_incoming_refs,
    get_law_structure,
    get_ref_graph,
    vector_search,
)
from src.models import (
    GraphEdge,
    GraphNode,
    LawStructureResult,
    ReadArticleResult,
    RefGraphResult,
    SearchArticlesResult,
    SearchResultItem,
)
from src.utils import (
    build_flat_response,
    build_law_structure,
    build_tiered_response,
    get_db,
    get_embedder,
    merge_search_results,
)

MAX_DEPTH = int(os.getenv("MAX_DEPTH", "3"))

_host = os.getenv("MCP_HOST", "127.0.0.1")
_port = int(os.getenv("MCP_PORT", "8000"))

mcp = FastMCP("Portuguese Legal Graph", host=_host, port=_port)


@mcp.tool()
def read_article(
    article_id: str,
    depth: int = 1,
    query: str | None = None,
    include_incoming: bool = False,
) -> ReadArticleResult:
    """Return an article with its referenced articles expanded to a configurable depth.

    Always pass `query` (the user's question or topic) to get relevance-tiered results:
    - critical_references: highly relevant articles, full text included
    - supporting_references: moderately relevant, summary + first paragraph
    - peripheral_references: low relevance, title and hint only

    Start with depth=1. Increase only if the answer requires following more chains of references.

    Args:
        article_id: Article ID, e.g. "cirs:art:22"
        depth: How many levels of references to expand (1-3, default 1)
        query: The user's question or topic — enables relevance-tiered expansion
        include_incoming: Also include articles that reference this one
    """
    depth = max(1, min(depth, MAX_DEPTH))

    with get_db() as session:
        data = get_article_with_refs(session, article_id, depth)
        incoming = get_incoming_refs(session, article_id) if include_incoming else None

    if not data:
        raise ValueError(f"Article '{article_id}' not found")

    root, raw_refs = data["root"], data.get("refs", [])

    if query:
        return build_tiered_response(root, raw_refs, query, article_id, incoming)
    return build_flat_response(root, raw_refs, article_id, incoming)


@mcp.tool()
def search_articles(
    query: str,
    law_id: str | None = None,
    limit: int = 10,
) -> SearchArticlesResult:
    """Search Portuguese legal articles by meaning, not just keywords.

    Use this to find articles about a topic when you don't know the specific article number.
    Combines full-text and semantic (vector) search for better results.

    Args:
        query: The topic or question to search for, e.g. "rendimentos categoria B"
        law_id: Restrict to a specific law, e.g. "cirs"
        limit: Max results (1-20, default 10)
    """
    limit = max(1, min(limit, 20))

    embedder = get_embedder()
    query_embedding = embedder.embed_query(query)

    with get_db() as session:
        ft_results = fulltext_search(session, query, law_id, limit)
        vec_results = vector_search(session, query_embedding, law_id, limit)

    merged = merge_search_results(ft_results, vec_results)

    return SearchArticlesResult(
        results=[
            SearchResultItem(
                id=r["id"],
                law_id=r.get("law_id", ""),
                number=r.get("number", ""),
                title=r.get("title"),
                summary_hint=r.get("summary_hint"),
                snippet=(r.get("text") or "")[:200],
                chapter=r.get("chapter"),
                ref_count=r.get("ref_count", 0),
                score=round(r["combined_score"], 4),
            )
            for r in merged[:limit]
        ]
    )


@mcp.tool()
def get_structure(law_id: str) -> LawStructureResult:
    """Return the hierarchical table of contents of a law.

    Args:
        law_id: Law ID, e.g. "cirs"
    """
    with get_db() as session:
        rows = get_law_structure(session, law_id)

    if not rows:
        raise ValueError(f"Law '{law_id}' not found or has no articles")

    return LawStructureResult(law_id=law_id, structure=build_law_structure(rows))


@mcp.tool()
def get_ref_graph_tool(article_id: str, depth: int = 2) -> RefGraphResult:
    """Return the reference graph around an article (no full text, topology only).

    Args:
        article_id: Article ID, e.g. "cirs:art:22"
        depth: How many hops to traverse (1-4, default 2)
    """
    depth = max(1, min(depth, 4))

    with get_db() as session:
        graph = get_ref_graph(session, article_id, depth)

    return RefGraphResult(
        nodes=[
            GraphNode(id=n["id"], title=n.get("title"), law_id=n.get("law_id", ""))
            for n in graph["nodes"]
        ],
        edges=[
            GraphEdge(
                source=e["source"], target=e["target"], ref_type=e.get("ref_type")
            )
            for e in graph["edges"]
        ],
    )


if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio")
    mcp.run(transport=transport)  # type: ignore[arg-type]
