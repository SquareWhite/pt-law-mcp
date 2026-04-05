from __future__ import annotations

from typing import Any

from neo4j import Driver, Session

from src.models import Article, Law, Reference

_BATCH_SIZE = 500


def upsert_law(session: Session, law: Law) -> None:
    session.run(
        """
        MERGE (l:Law {id: $id})
        SET l.full_name = $full_name,
            l.short_name = $short_name,
            l.diploma_type = $diploma_type,
            l.diploma_number = $diploma_number,
            l.eli_uri = $eli_uri
        """,
        **law.model_dump(),
    )


def upsert_articles(session: Session, articles: list[Article]) -> None:
    data = [a.model_dump() for a in articles]
    for i in range(0, len(data), _BATCH_SIZE):
        batch = data[i : i + _BATCH_SIZE]
        session.run(
            """
            UNWIND $batch AS a
            MERGE (art:Article {id: a.id})
            SET art.law_id   = a.law_id,
                art.number   = a.number,
                art.title    = a.title,
                art.text     = a.text,
                art.chapter  = a.chapter,
                art.section  = a.section
            WITH art, a
            MATCH (l:Law {id: a.law_id})
            MERGE (art)-[:BELONGS_TO]->(l)
            """,
            batch=batch,
        )


def upsert_references(session: Session, refs: list[Reference]) -> None:
    data = [r.model_dump() for r in refs]
    for i in range(0, len(data), _BATCH_SIZE):
        batch = data[i : i + _BATCH_SIZE]
        session.run(
            """
            UNWIND $batch AS r
            MATCH (src:Article {id: r.source_id})
            MATCH (tgt:Article {id: r.target_id})
            MERGE (src)-[rel:REFERENCES {source_id: r.source_id, target_id: r.target_id}]->(tgt)
            SET rel.context         = r.context,
                rel.ref_type        = r.ref_type,
                rel.target_fragment = r.target_fragment
            """,
            batch=batch,
        )


def delete_refs_from(session: Session, article_ids: list[str]) -> None:
    session.run(
        """
        UNWIND $ids AS id
        MATCH (a:Article {id: id})-[r:REFERENCES]->()
        DELETE r
        """,
        ids=article_ids,
    )


def get_article(session: Session, article_id: str) -> Article | None:
    result = session.run(
        "MATCH (a:Article {id: $id}) RETURN a", id=article_id
    )
    record = result.single()
    if record is None:
        return None
    return Article(**dict(record["a"]))


def get_article_with_refs(
    session: Session, article_id: str, depth: int
) -> dict:
    depth = max(1, min(depth, 3))
    result = session.run(
        f"""
        MATCH (root:Article {{id: $id}})
        OPTIONAL MATCH path = (root)-[:REFERENCES*1..{depth}]->(ref:Article)
        RETURN root,
               collect(DISTINCT {{
                   node: ref,
                   depth: length(path),
                   edge: last(relationships(path)),
                   out_ref_count: COUNT {{ (ref)-[:REFERENCES]->() }}
               }}) AS refs
        """,
        id=article_id,
    )
    record = result.single()
    if record is None:
        return {}
    root = dict(record["root"])
    expanded = [
        {
            "article": dict(r["node"]) if r["node"] else None,
            "depth": r["depth"],
            "context": dict(r["edge"]).get("context") if r["edge"] else None,
            "ref_type": dict(r["edge"]).get("ref_type") if r["edge"] else None,
            "target_fragment": dict(r["edge"]).get("target_fragment") if r["edge"] else None,
            "out_ref_count": r.get("out_ref_count", 0),
        }
        for r in record["refs"]
        if r["node"] is not None
    ]
    return {"root": root, "refs": expanded}


def get_incoming_refs(session: Session, article_id: str) -> list[dict]:
    result = session.run(
        """
        MATCH (src:Article)-[r:REFERENCES]->(tgt:Article {id: $id})
        RETURN src, r
        """,
        id=article_id,
    )
    return [
        {
            "article": dict(record["src"]),
            "context": record["r"]["context"],
            "ref_type": record["r"]["ref_type"],
        }
        for record in result
    ]


def fulltext_search(
    session: Session,
    query: str,
    law_id: str | None,
    limit: int,
) -> list[dict]:
    if law_id:
        result = session.run(
            """
            CALL db.index.fulltext.queryNodes('article_text', $q)
            YIELD node, score
            WHERE node.law_id = $law_id
            WITH node, score
            ORDER BY score DESC
            LIMIT $limit
            OPTIONAL MATCH (node)-[r:REFERENCES]->()
            RETURN node, score, count(r) AS ref_count
            """,
            q=query,
            law_id=law_id,
            limit=limit,
        )
    else:
        result = session.run(
            """
            CALL db.index.fulltext.queryNodes('article_text', $q)
            YIELD node, score
            WITH node, score
            ORDER BY score DESC
            LIMIT $limit
            OPTIONAL MATCH (node)-[r:REFERENCES]->()
            RETURN node, score, count(r) AS ref_count
            """,
            q=query,
            limit=limit,
        )
    return [
        {**dict(record["node"]), "ref_count": record["ref_count"], "score": record["score"]}
        for record in result
    ]


def get_law_structure(session: Session, law_id: str) -> list[dict]:
    result = session.run(
        """
        MATCH (l:Law {id: $law_id})<-[:BELONGS_TO]-(a:Article)
        RETURN a.chapter AS chapter, a.section AS section,
               a.number AS number, a.title AS title, a.id AS id
        ORDER BY a.id
        """,
        law_id=law_id,
    )
    return [dict(record) for record in result]


def get_ref_graph(session: Session, article_id: str, depth: int) -> dict:
    depth = max(1, min(depth, 4))
    result = session.run(
        f"""
        MATCH (root:Article {{id: $id}})
        OPTIONAL MATCH (root)-[:REFERENCES*1..{depth}]-(connected:Article)
        WITH root, collect(DISTINCT connected) AS connected_nodes
        WITH connected_nodes + [root] AS all_nodes
        UNWIND all_nodes AS n
        OPTIONAL MATCH (n)-[r:REFERENCES]->(m:Article)
        WHERE m IN all_nodes
        RETURN collect(DISTINCT {{
                   id: n.id, title: n.title, law_id: n.law_id
               }}) AS nodes,
               collect(DISTINCT {{
                   source: r.source_id, target: r.target_id, ref_type: r.ref_type
               }}) AS edges
        """,
        id=article_id,
    )
    record = result.single()
    if record is None:
        return {"nodes": [], "edges": []}
    return {
        "nodes": [n for n in record["nodes"] if n["id"] is not None],
        "edges": [e for e in record["edges"] if e["source"] is not None],
    }


def get_unreferenced_law_ids(session: Session) -> list[str]:
    """Return law IDs that appear in REFERENCES edges but have no Law node."""
    result = session.run(
        """
        MATCH (a:Article)-[:REFERENCES]->(b:Article)
        WITH collect(DISTINCT a.law_id) + collect(DISTINCT b.law_id) AS referenced_law_ids
        UNWIND referenced_law_ids AS law_id
        WITH DISTINCT law_id
        WHERE law_id IS NOT NULL AND NOT EXISTS { MATCH (:Law {id: law_id}) }
        RETURN law_id
        ORDER BY law_id
        """
    )
    return [record["law_id"] for record in result]


def embed_missing_articles(driver: Driver, embedder: Any) -> int:
    from src.embeddings import prepare_embedding_text

    with driver.session() as session:
        result = session.run(
            """
            MATCH (a:Article)
            WHERE a.embedding IS NULL
            RETURN a.id AS id, a.text AS text, a.title AS title,
                   a.chapter AS chapter, a.section AS section
            """
        )
        rows = [dict(r) for r in result]

    if not rows:
        return 0

    texts = [prepare_embedding_text(row) for row in rows]
    embeddings = embedder.embed_texts(texts)

    with driver.session() as session:
        for i in range(0, len(rows), _BATCH_SIZE):
            batch = [
                {"id": rows[j]["id"], "embedding": embeddings[j]}
                for j in range(i, min(i + _BATCH_SIZE, len(rows)))
            ]
            session.run(
                """
                UNWIND $batch AS item
                MATCH (a:Article {id: item.id})
                CALL db.create.setNodeVectorProperty(a, 'embedding', item.embedding)
                SET a.embedded_at = datetime()
                """,
                batch=batch,
            )

    return len(rows)


def null_embeddings(session: Session, article_ids: list[str]) -> None:
    session.run(
        """
        UNWIND $ids AS id
        MATCH (a:Article {id: id})
        SET a.embedding = null, a.embedded_at = null
        """,
        ids=article_ids,
    )


def vector_search(
    session: Session,
    query_embedding: list[float],
    law_id: str | None,
    limit: int,
) -> list[dict]:
    if law_id:
        result = session.run(
            """
            CALL db.index.vector.queryNodes('article_embeddings', $k, $embedding)
            YIELD node AS article, score AS vector_score
            WHERE article.law_id = $law_id
            RETURN article, vector_score
            """,
            k=limit,
            embedding=query_embedding,
            law_id=law_id,
        )
    else:
        result = session.run(
            """
            CALL db.index.vector.queryNodes('article_embeddings', $k, $embedding)
            YIELD node AS article, score AS vector_score
            RETURN article, vector_score
            """,
            k=limit,
            embedding=query_embedding,
        )
    return [
        {
            **dict(record["article"]),
            "vector_score": record["vector_score"],
        }
        for record in result
    ]


def load_hints(session: Session, hints: list[dict]) -> None:
    session.run(
        """
        UNWIND $hints AS h
        MATCH (a:Article {id: h.id})
        SET a.summary_hint = h.summary_hint
        """,
        hints=hints,
    )


def export_articles_without_hints(
    session: Session, law_id: str | None
) -> list[dict]:
    if law_id:
        result = session.run(
            """
            MATCH (a:Article)
            WHERE a.summary_hint IS NULL AND a.law_id = $law_id
            RETURN a.id AS id, a.text AS text
            """,
            law_id=law_id,
        )
    else:
        result = session.run(
            """
            MATCH (a:Article)
            WHERE a.summary_hint IS NULL
            RETURN a.id AS id, a.text AS text
            """
        )
    return [dict(r) for r in result]


def get_stats(session: Session) -> dict:
    result = session.run(
        """
        MATCH (l:Law) WITH count(l) AS law_count
        MATCH (a:Article) WITH law_count, count(a) AS article_count
        MATCH ()-[r:REFERENCES]->() WITH law_count, article_count, count(r) AS ref_count
        RETURN law_count, article_count, ref_count
        """
    )
    record = result.single()
    if record is None:
        return {"law_count": 0, "article_count": 0, "ref_count": 0}
    return dict(record)


def get_top_referenced_articles(session: Session, limit: int = 10) -> list[dict]:
    result = session.run(
        """
        MATCH (a:Article)<-[:REFERENCES]-()
        RETURN a.id AS id, a.title AS title, count(*) AS incoming_count
        ORDER BY incoming_count DESC
        LIMIT $limit
        """,
        limit=limit,
    )
    return [dict(r) for r in result]


def get_orphan_article_count(session: Session) -> int:
    result = session.run(
        """
        MATCH (a:Article)
        WHERE NOT (a)-[:REFERENCES]->()
        RETURN count(a) AS orphan_count
        """
    )
    record = result.single()
    return record["orphan_count"] if record else 0
