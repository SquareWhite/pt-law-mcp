from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

from src.db.connection import get_driver, get_session
from src.db.repository import (
    delete_refs_from,
    embed_missing_articles,
    export_articles_without_hints,
    get_orphan_article_count,
    get_stats,
    get_top_referenced_articles,
    load_hints,
    null_embeddings,
    upsert_articles,
    upsert_law,
    upsert_references,
)
from src.db.schema import apply_schema
from src.models import AmbiguousReference, Article, Law, Reference
from src.parser.article_splitter import split_articles
from src.parser.epub_reader import read_epub
from src.parser.pdf_reader import read_pdf
from src.parser.ref_extractor import extract_refs

AMBIGUOUS_FILE = Path("ambiguous_refs.json")


def _read_source(file_path: str) -> list[tuple[str, str]]:
    path = Path(file_path)
    if path.suffix.lower() == ".pdf":
        return read_pdf(path)
    return read_epub(path)


def _ingest_as_single_document(
    chapters: list[tuple[str, str]], law_id: str, title: str
) -> list[Article]:
    """Return the entire document as one Article — no splitting."""
    from bs4 import BeautifulSoup

    parts: list[str] = []
    for _, html in chapters:
        soup = BeautifulSoup(html, "lxml")
        parts.append(soup.get_text("\n", strip=True))
    return [
        Article(
            id=f"{law_id}:art:1",
            law_id=law_id,
            number="1",
            title=title,
            text="\n\n".join(parts),
        )
    ]


def _load_ambiguous() -> list[dict]:
    if AMBIGUOUS_FILE.exists():
        return json.loads(AMBIGUOUS_FILE.read_text())
    return []


def _save_ambiguous(records: list[dict]) -> None:
    AMBIGUOUS_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2))


def _resolve_relative_refs(
    articles: list, ambiguous: list[AmbiguousReference]
) -> list[Reference]:
    """Resolve 'artigo anterior/seguinte' using document order from the parsed article list."""
    article_ids = [a.id for a in articles]
    id_to_idx = {a.id: i for i, a in enumerate(articles)}

    resolved: list[Reference] = []
    seen: set[tuple[str, str]] = set()

    for amb in ambiguous:
        if amb.reason != "relative reference":
            continue
        raw = amb.raw_text.lower()
        source_idx = id_to_idx.get(amb.source_id)
        if source_idx is None:
            continue

        if "anterior" in raw:
            if source_idx == 0:
                continue
            target_id = article_ids[source_idx - 1]
        elif "seguinte" in raw:
            if source_idx >= len(article_ids) - 1:
                continue
            target_id = article_ids[source_idx + 1]
        else:
            continue

        key = (amb.source_id, target_id)
        if key in seen:
            continue
        seen.add(key)

        resolved.append(
            Reference(
                source_id=amb.source_id,
                target_id=target_id,
                context=amb.raw_text,
                ref_type="remissão",
            )
        )

    return resolved



def cmd_load(args: argparse.Namespace) -> None:
    driver = get_driver()
    apply_schema(driver)

    diploma_type, diploma_number = args.diploma.split(":", 1)
    law = Law(
        id=args.law_id,
        full_name=args.full_name,
        short_name=args.short_name,
        diploma_type=diploma_type,
        diploma_number=diploma_number,
    )

    chapters = _read_source(args.file)
    parser = getattr(args, "parser", "auto")
    if parser == "portaria":
        articles = _ingest_as_single_document(chapters, args.law_id, args.full_name)
    else:
        articles = split_articles(chapters, args.law_id)

    all_refs: list[Reference] = []
    all_ambiguous: list[AmbiguousReference] = []
    for article in articles:
        refs, ambiguous = extract_refs(article)
        all_refs.extend(refs)
        all_ambiguous.extend(ambiguous)

    additional = _resolve_relative_refs(articles, all_ambiguous)
    all_refs.extend(additional)

    resolved_keys = {(r.source_id, r.context.lower()) for r in additional}
    remaining_ambiguous = [
        a for a in all_ambiguous
        if (a.source_id, a.raw_text.lower()) not in resolved_keys
    ]

    with get_session() as session:
        upsert_law(session, law)
        upsert_articles(session, articles)
        delete_refs_from(session, [a.id for a in articles])
        upsert_references(session, all_refs)

    _save_ambiguous([a.model_dump() for a in remaining_ambiguous])

    from src.embeddings import EmbeddingService
    embedder = EmbeddingService()
    embedded = embed_missing_articles(driver, embedder)

    logger.info(
        "Loaded %d articles, %d references (%d from relative), "
        "%d ambiguous references, %d articles embedded",
        len(articles), len(all_refs), len(additional),
        len(all_ambiguous), embedded,
    )


def cmd_update(args: argparse.Namespace) -> None:
    driver = get_driver()
    apply_schema(driver)

    target_numbers = set(args.articles.split(","))
    chapters = _read_source(args.file)
    all_articles = split_articles(chapters, args.law_id)  # update only supports standard laws
    articles = [a for a in all_articles if a.number in target_numbers]

    if not articles:
        logger.error("No matching articles found.")
        sys.exit(1)

    all_refs: list[Reference] = []
    new_ambiguous: list[AmbiguousReference] = []
    for article in articles:
        refs, ambiguous = extract_refs(article)
        all_refs.extend(refs)
        new_ambiguous.extend(ambiguous)

    # Resolve relative refs using full-law sequence for correct prev/next context
    additional = _resolve_relative_refs(all_articles, new_ambiguous)
    # Filter to only those whose source is in the updated set
    updated_ids = {a.id for a in articles}
    additional = [r for r in additional if r.source_id in updated_ids]
    all_refs.extend(additional)

    resolved_keys = {(r.source_id, r.context.lower()) for r in additional}
    remaining_ambiguous = [
        a for a in new_ambiguous
        if (a.source_id, a.raw_text.lower()) not in resolved_keys
    ]

    updated_ids = [a.id for a in articles]
    with get_session() as session:
        upsert_articles(session, articles)
        null_embeddings(session, updated_ids)
        delete_refs_from(session, updated_ids)
        upsert_references(session, all_refs)

    existing = _load_ambiguous()
    existing.extend([a.model_dump() for a in remaining_ambiguous])
    _save_ambiguous(existing)

    from src.embeddings import EmbeddingService
    embedder = EmbeddingService()
    embedded = embed_missing_articles(driver, embedder)

    logger.info(
        "Updated %d articles, %d references (%d from relative), "
        "%d new ambiguous references, %d articles embedded",
        len(articles), len(all_refs), len(additional),
        len(remaining_ambiguous), embedded,
    )


def cmd_resolve(args: argparse.Namespace) -> None:
    records = json.loads(Path(args.file).read_text())
    refs = [Reference(**r) for r in records]

    with get_session() as session:
        upsert_references(session, refs)

    logger.info("Resolved %d references.", len(refs))


def cmd_load_all(args: argparse.Namespace) -> None:
    config_path = Path(args.config)
    laws_config = json.loads(config_path.read_text())

    for entry in laws_config:
        file_path = Path(entry.get("pdf_file") or entry.get("epub_file", ""))
        if not file_path or not file_path.exists():
            logger.warning("SKIP %s: %s not found", entry["law_id"], file_path)
            continue
        logger.info("Loading %s from %s ...", entry["law_id"], file_path)
        load_args = argparse.Namespace(
            command="load",
            law_id=entry["law_id"],
            short_name=entry["short_name"],
            full_name=entry["full_name"],
            diploma=entry["diploma"],
            file=str(file_path),
            parser=entry.get("parser", "auto"),
        )
        cmd_load(load_args)



def cmd_embed_missing(_args: argparse.Namespace) -> None:
    from src.embeddings import EmbeddingService
    embedder = EmbeddingService()
    driver = get_driver()
    apply_schema(driver)
    count = embed_missing_articles(driver, embedder)
    logger.info("Embedded %d articles.", count)


def cmd_export_articles(args: argparse.Namespace) -> None:
    with get_session() as session:
        articles = export_articles_without_hints(session, args.law_id)
    output = Path(args.output)
    output.write_text(json.dumps(articles, ensure_ascii=False, indent=2))
    logger.info("Exported %d articles to %s", len(articles), output)


def cmd_load_hints(args: argparse.Namespace) -> None:
    hints = json.loads(Path(args.file).read_text())
    with get_session() as session:
        load_hints(session, hints)
    logger.info("Loaded %d hints.", len(hints))


def cmd_load_hints_dir(args: argparse.Namespace) -> None:
    hints_dir = Path(args.dir)
    total = 0
    for json_file in sorted(hints_dir.glob("*.json")):
        hints = json.loads(json_file.read_text())
        with get_session() as session:
            load_hints(session, hints)
        total += len(hints)
        logger.info("  Loaded %d hints from %s", len(hints), json_file.name)
    logger.info("Total hints loaded: %d", total)


def cmd_stats(_args: argparse.Namespace) -> None:
    with get_session() as session:
        stats = get_stats(session)
        top = get_top_referenced_articles(session)
        orphan_count = get_orphan_article_count(session)

    ambiguous_count = len(_load_ambiguous())

    print(f"Laws:               {stats.get('law_count', 0)}")
    print(f"Articles:           {stats.get('article_count', 0)}")
    print(f"References:         {stats.get('ref_count', 0)}")
    print(f"Ambiguous refs:     {ambiguous_count}")
    print(f"Orphan articles:    {orphan_count}  (no outgoing refs)")
    print()
    print("Top 10 most-referenced articles:")
    for i, row in enumerate(top, 1):
        title = row.get("title") or ""
        title_part = f"  {title[:50]}" if title else ""
        print(f"  {i:2}. {row['id']} ({row['incoming_count']} refs){title_part}")


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    parser = argparse.ArgumentParser(prog="src.ingest")
    sub = parser.add_subparsers(dest="command", required=True)

    # load
    p_load = sub.add_parser("load")
    p_load.add_argument("--law-id", required=True)
    p_load.add_argument("--short-name", required=True)
    p_load.add_argument("--full-name", required=True)
    p_load.add_argument("--diploma", required=True, help="type:number e.g. decreto-lei:442-A/88")
    p_load.add_argument("--file", required=True)
    p_load.add_argument("--parser", default="auto", choices=["auto", "portaria"],
                        help="Parser to use: 'auto' splits into articles, 'portaria' ingests as single document")

    # update
    p_update = sub.add_parser("update")
    p_update.add_argument("--law-id", required=True)
    p_update.add_argument("--articles", required=True, help="comma-separated article numbers")
    p_update.add_argument("--file", required=True)

    # resolve
    p_resolve = sub.add_parser("resolve")
    p_resolve.add_argument("--file", required=True)

    # load-all
    p_load_all = sub.add_parser("load-all")
    p_load_all.add_argument(
        "--config", default="laws.json", help="Path to laws config JSON"
    )

    # stats
    sub.add_parser("stats")

    # embed-missing
    sub.add_parser("embed-missing")

    # export-articles
    p_export = sub.add_parser("export-articles")
    p_export.add_argument("--law-id", default=None)
    p_export.add_argument("--output", required=True)

    # load-hints
    p_hints = sub.add_parser("load-hints")
    p_hints.add_argument("--file", required=True)

    # load-hints-dir
    p_hints_dir = sub.add_parser("load-hints-dir")
    p_hints_dir.add_argument("--dir", required=True)

    args = parser.parse_args()
    # Normalise dashes to underscores in namespace
    args_dict = {k.replace("-", "_"): v for k, v in vars(args).items()}
    args = argparse.Namespace(**args_dict)

    dispatch = {
        "load": cmd_load,
        "load-all": cmd_load_all,
        "update": cmd_update,
        "resolve": cmd_resolve,
        "stats": cmd_stats,
        "embed-missing": cmd_embed_missing,
        "export-articles": cmd_export_articles,
        "load-hints": cmd_load_hints,
        "load-hints-dir": cmd_load_hints_dir,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
