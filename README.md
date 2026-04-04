# Portuguese Legal Graph MCP

Navigates Portuguese tax law as a graph. EPUBs are parsed into articles and cross-references, stored in Neo4j, and exposed via an MCP server so an LLM can read any article with its referenced articles automatically expanded.

14 Portuguese tax laws are supported: CIRS, CIRC, CIVA, LGT, CPPT, EBF, CIS, CIMI, CIMT, CIUC, CFI, RGIT, RCPITA, RJAMT.

## How it works

```
EPUBs → ingest (parse + extract refs + embed) → Neo4j ← MCP server ← Claude / any MCP client
```

Articles are embedded with `intfloat/multilingual-e5-base` at ingest time. When you call `read_article` with a query, referenced articles are ranked by semantic relevance and split into critical / supporting / peripheral tiers so the LLM sees the most relevant content first.

## Run

```bash
cp .env.example .env
docker compose up
```

On first start, EPUBs listed in `laws.json` are automatically ingested (articles parsed, cross-references extracted, embeddings computed) before the MCP server comes up. Drop EPUB files into `epubs/` and add entries to `laws.json` to add more laws.

## Neo4j Browser

Open [http://localhost:7474](http://localhost:7474) and log in with `neo4j` / `legalGraphDev`.

```cypher
MATCH (a:Article)-[r:REFERENCES]->(b:Article)
RETURN a, r, b LIMIT 50
```

## Connect to Claude

Add this to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "portuguese-law": {
      "url": "http://localhost:8000/sse"
    }
  }
}
```

## MCP tools

| Tool | What it does |
|------|-------------|
| `read_article` | Returns an article with referenced articles expanded. Pass `query` to get relevance-tiered results (critical / supporting / peripheral). |
| `search_articles` | Hybrid full-text + semantic (vector) search over all articles. |
| `get_structure` | Returns the table of contents hierarchy of a law. |
| `get_ref_graph_tool` | Returns the reference topology around an article (no body text, lightweight). |

### `read_article` in detail

```
read_article(article_id, depth=1, query=None, include_incoming=False)
```

Always pass `query` (the user's question) to activate tiered expansion:

- **critical_references** — highest semantic similarity to the query, full text included
- **supporting_references** — moderate similarity, first paragraph only
- **peripheral_references** — low similarity, title and hint only

Start with `depth=1`. Increase only if following more reference chains is needed.

Example prompt: *"Explain how categoria B income is taxed under CIRS, starting from article 3."*

## Summary hints

Each article can have a one-line orientation label (`summary_hint`), e.g. `"Define quem está sujeito a tributação em IRS"`. These are generated externally with Claude and loaded via JSON:

```bash
# Export articles needing hints
docker compose exec mcp-server \
  python -m src.ingest export-articles --law-id cirs --output /tmp/cirs_articles.json

# Generate hints with Claude, save as /tmp/cirs_hints.json, then load:
docker compose exec mcp-server \
  python -m src.ingest load-hints --file /tmp/cirs_hints.json
```

Or drop pre-generated `*.json` files into `hints/` — they load automatically on container start.

## Ingest CLI

```bash
# Load a single law from an EPUB
python -m src.ingest load --law-id cirs --short-name CIRS --full-name "Código do IRS" \
  --diploma decreto-lei:442-A/88 --file epubs/cirs.epub

# Load all laws configured in laws.json
python -m src.ingest load-all

# Update specific articles without re-ingesting the whole law
python -m src.ingest update --law-id cirs --articles 22,23 --file epubs/cirs.epub

# Show stats (article counts, top-referenced articles, orphans)
python -m src.ingest stats

# Compute embeddings for any articles missing them
python -m src.ingest embed-missing
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | |
| `NEO4J_USER` | `neo4j` | |
| `NEO4J_PASSWORD` | `legalGraphDev` | |
| `EMBEDDING_MODEL` | `intfloat/multilingual-e5-base` | Sentence-transformers model for embeddings |
| `MCP_HOST` | `127.0.0.1` | |
| `MCP_PORT` | `8000` | |
| `MCP_TRANSPORT` | `stdio` | `stdio` or `sse` |
| `MAX_DEPTH` | `3` | Max reference expansion depth |
| `TOKEN_BUDGET` | `8000` | Max words in flat `read_article` response |
| `CRITICAL_THRESHOLD` | `0.5` | Normalised cosine sim threshold for critical refs |
| `SUPPORTING_THRESHOLD` | `0.3` | Normalised cosine sim threshold for supporting refs |
| `LOG_LEVEL` | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `TRANSFORMERS_OFFLINE` | _(unset)_ | Set to `1` to prevent HuggingFace network round-trips |

## Running locally (outside Docker)

```bash
cp .env.example .env  # edit NEO4J_* vars
pip install -e .
python -m src.ingest load-all
python -m src.server
```
