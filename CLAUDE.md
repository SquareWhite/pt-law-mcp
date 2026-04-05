# Portuguese Legal Graph MCP

## What this project is

A local MCP server that ingests Portuguese tax law EPUBs, parses them into individual articles, extracts cross-references between articles, and stores everything as a graph in Neo4j. LLM clients (e.g. Claude Desktop) connect via MCP and use the exposed tools to navigate the law graph with automatic reference expansion.

The whole system runs via `docker compose up` — no manual steps beyond dropping source files into `data/epubs/` or `data/pdfs/`.

## Laws covered

14 Portuguese tax laws defined in `laws.json`:

| ID | Short name | Full name |
|----|-----------|-----------|
| cirs | CIRS | Código do IRS (personal income tax) |
| circ | CIRC | Código do IRC (corporate income tax) |
| civa | CIVA | Código do IVA (VAT) |
| lgt | LGT | Lei Geral Tributária (general tax framework) |
| cppt | CPPT | Código de Procedimento e Processo Tributário |
| ebf | EBF | Estatuto dos Benefícios Fiscais |
| cis | CIS | Código do Imposto do Selo (stamp duty) |
| cimi | CIMI | Código do IMI (property tax) |
| cimt | CIMT | Código do IMT (property transfer tax) |
| ciuc | CIUC | Código do IUC (vehicle tax) |
| cfi | CFI | Código Fiscal do Investimento |
| rgit | RGIT | Regime Geral das Infrações Tributárias |
| rcpita | RCPITA | Regime de Inspeção Tributária e Aduaneira |
| rjamt | RJAMT | Regime Jurídico da Arbitragem Tributária |

## Architecture

```
data/{epubs,pdfs}/ → ingest.py → parse articles → extract cross-refs → Neo4j graph
                                                               ↑
                                         MCP server (tools) ←─┘
```

**Neo4j graph model:**
- `(:Law)` nodes — one per law
- `(:Article)` nodes — one per article, with `id` like `cirs:art:22`
- `(:Article)-[:BELONGS_TO]->(:Law)`
- `(:Article)-[:REFERENCES {context, ref_type, target_fragment}]->(:Article)`

**Article IDs:** `{law_id}:art:{number}` e.g. `cirs:art:88-A`, `lgt:art:30`

**Reference types:** `remissão` (cross-reference), `exceção` (exception), `aplicação` (application)

## Key files

```
src/
├── embeddings.py          EmbeddingService (sentence-transformers, e5 model)
├── models.py              Pydantic models: Law, Article, Reference, AmbiguousReference
├── ingest.py              CLI: load, update, resolve, load-all, stats, embed-missing,
│                                export-articles, load-hints, load-hints-dir
├── server.py              FastMCP server — 4 tools exposed
├── parser/
│   ├── epub_reader.py     EPUB → list of (chapter_title, html) tuples
│   ├── article_splitter.py HTML → list[Article], tracks chapter/section context
│   └── ref_extractor.py   Article text → References + AmbiguousReferences (regex-based)
└── db/
    ├── connection.py      Neo4j driver singleton + get_session() context manager
    ├── schema.py          Constraints, fulltext index, vector index
    └── repository.py      All Neo4j queries
data/
├── epubs/                 Drop EPUB files here (gitignored)
├── pdfs/                  Drop PDF files here (gitignored)
└── hints/                 Drop summary hint JSON files here (gitignored)
laws.json                  Law metadata + epub paths for load-all
entrypoint.sh              Docker startup sequence
```

## MCP tools

**`read_article(article_id, depth=1, query=None, include_incoming=False)`**
Returns an article with its cross-referenced articles expanded up to `depth` levels. When `query` is provided, referenced articles are tiered by semantic relevance (cosine similarity against stored embeddings): critical (≥0.5, full text), supporting (0.3–0.49, snippet), peripheral (<0.3, title only).

**`search_articles(query, law_id=None, limit=10)`**
Hybrid search: combines fulltext (Lucene) and vector (cosine similarity) scores. Returns article IDs, titles, and summary hints.

**`get_structure(law_id)`**
Returns the hierarchical TOC of a law (chapters → sections → articles).

**`get_ref_graph_tool(article_id, depth=2)`**
Returns the reference topology (nodes + edges) without article text — lightweight graph overview.

## Embedding model

`intfloat/multilingual-e5-base` (768 dimensions, ~900MB RAM). Configured via `EMBEDDING_MODEL` env var. Pre-downloaded at Docker build time. Embeddings are computed during ingestion and stored on `Article` nodes. e5 models require prefixes: `"passage: "` at ingestion, `"query: "` at search time.

## Summary hints

Short orientation labels on each article (e.g. `"Define quem está sujeito a tributação em IRS"`). Generated externally with Claude and loaded via JSON:
```bash
python -m src.ingest export-articles --law-id cirs --output cirs_articles.json
# generate hints with Claude → cirs_hints.json
python -m src.ingest load-hints --file cirs_hints.json
```

## Running locally (outside Docker)

```bash
cp .env.example .env  # edit NEO4J_* vars
pip install -e .
python -m src.ingest load-all
python -m src.ingest embed-missing
python -m src.server
```

## Docker

```bash
docker compose up        # builds, ingests configured EPUBs, embeds, starts MCP server
```

Port 8000: MCP server (SSE transport). Port 7474: Neo4j browser. Port 7687: Neo4j Bolt.

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | |
| `NEO4J_USER` | `neo4j` | |
| `NEO4J_PASSWORD` | `legalGraphDev` | |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` | |
| `MCP_PORT` | `8000` | |
| `MAX_DEPTH` | `3` | Max reference expansion depth |
| `TOKEN_BUDGET` | `8000` | Max words in read_article response |
| `CRITICAL_THRESHOLD` | `0.5` | Cosine sim threshold for critical refs |
| `SUPPORTING_THRESHOLD` | `0.3` | Cosine sim threshold for supporting refs |

## Ambiguous references

References like "artigo anterior" that can't be resolved by regex alone are saved to `ambiguous_refs.json`. Relative references (previous/next article) are resolved automatically using document order. Law-level references (no specific article number) remain ambiguous.

## Plans

- `PLAN.md` — full implementation plan including PRD v2 (embeddings, hybrid search, tiered read_article)
- `PRD.md` — original PRD (v1)
- `PRD_V2.md` — PRD v2 spec (embeddings + query-aware expansion)
