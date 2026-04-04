from __future__ import annotations

from neo4j import Driver


def apply_schema(driver: Driver) -> None:
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT article_id IF NOT EXISTS "
            "FOR (a:Article) REQUIRE a.id IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT law_id IF NOT EXISTS "
            "FOR (l:Law) REQUIRE l.id IS UNIQUE"
        )
        session.run(
            "CREATE FULLTEXT INDEX article_text IF NOT EXISTS "
            "FOR (a:Article) ON EACH [a.text, a.title]"
        )
        session.run(
            """
            CREATE VECTOR INDEX article_embeddings IF NOT EXISTS
            FOR (a:Article) ON (a.embedding)
            OPTIONS {indexConfig: {
              `vector.dimensions`: 768,
              `vector.similarity_function`: 'cosine'
            }}
            """
        )
