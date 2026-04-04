#!/bin/sh
set -e

echo "Waiting for Neo4j Bolt to be ready..."
until python3 -c "
import sys
from neo4j import GraphDatabase
try:
    d = GraphDatabase.driver('$NEO4J_URI', auth=('$NEO4J_USER', '$NEO4J_PASSWORD'))
    d.verify_connectivity()
    d.close()
    sys.exit(0)
except Exception as e:
    print(e)
    sys.exit(1)
" 2>/dev/null; do
  sleep 2
done
echo "Neo4j is ready."

echo "Running ingestion from laws.json..."
python -m src.ingest load-all --config laws.json

echo "Embedding articles without embeddings..."
python -m src.ingest embed-missing

echo "Loading summary hints..."
python -m src.ingest load-hints-dir --dir /app/hints

echo "Starting MCP server..."
exec python -m src.server
