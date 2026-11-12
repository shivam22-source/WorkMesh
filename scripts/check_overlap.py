"""Verify that semantic paraphrase queries in queries_v2.jsonl share at most 1 content word
with any of their gold chunks.

Can check chunk text directly from PostgreSQL (default) or against the deterministic
in-code v2 corpus definition (`--offline`) during unit/CI validation.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RAG_PYTHON_DIR = REPO_ROOT / "rag-python"
if str(RAG_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_PYTHON_DIR))

STOPWORDS: set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "also", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below", "between",
    "both", "but", "by", "can", "could", "did", "do", "does", "doing", "down", "during",
    "each", "few", "for", "from", "further", "had", "has", "have", "having", "he", "her",
    "here", "hers", "herself", "him", "himself", "his", "how", "i", "if", "in", "into",
    "is", "it", "its", "itself", "just", "make", "made", "may", "me", "might", "more",
    "most", "my", "myself", "no", "nor", "not", "now", "of", "off", "on", "once", "only",
    "or", "other", "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should",
    "so", "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "use", "used", "using", "very", "was", "we", "were", "what", "when",
    "where", "which", "while", "who", "whom", "why", "will", "with", "would", "you", "your",
    "yours", "yourself", "yourselves",
}


def extract_content_words(text: str) -> set[str]:
    """Extract lowercased alphanumeric non-stopword content tokens."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return {t for t in tokens if len(t) > 1 and t not in STOPWORDS}


def compute_overlap(query: str, chunk_content: str) -> set[str]:
    """Return shared content words between a query and a target chunk."""
    return extract_content_words(query) & extract_content_words(chunk_content)


def load_queries_jsonl(path: Path) -> list[dict]:
    records: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                records.append(json.loads(stripped))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_num} of {path}: {exc}") from exc
    return records


def _fetch_chunks_from_postgres(chunk_ids: Iterable[str], db_url: str | None) -> dict[str, str]:
    import psycopg

    from app.cli.scale_benchmark import resolve_postgres_url

    dsn = resolve_postgres_url(db_url)
    ids = sorted(set(chunk_ids))
    if not ids:
        return {}
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT id, content FROM chunks WHERE id = ANY(%s);", (ids,))
        return {row[0]: row[1] for row in cur.fetchall()}


def _fetch_chunks_offline() -> dict[str, str]:
    from app.evaluation.corpus_v2 import build_v2_extension_records

    _, chunks, _, _, _ = build_v2_extension_records(embedder=None)
    return {c.id: c.content for c in chunks}


def verify_semantic_overlap(
    queries_path: Path,
    max_overlap: int = 1,
    offline: bool = False,
    db_url: str | None = None,
) -> tuple[int, list[str]]:
    """Validate that every semantic query has <= max_overlap content words with each gold chunk."""
    records = load_queries_jsonl(queries_path)
    semantic_queries = [r for r in records if r.get("category") == "semantic"]

    gold_ids = [cid for r in semantic_queries for cid in r.get("qrels", {}).keys()]
    chunk_texts = (
        _fetch_chunks_offline()
        if offline
        else _fetch_chunks_from_postgres(gold_ids, db_url=db_url)
    )

    failures: list[str] = []
    for item in semantic_queries:
        qid = item["id"]
        query = item["query"]
        qrels = item.get("qrels", {})
        if not qrels:
            failures.append(f"{qid}: no gold qrels defined")
            continue
        for cid, grade in qrels.items():
            if grade <= 0:
                continue
            content = chunk_texts.get(cid)
            if content is None:
                failures.append(f"{qid}: gold chunk '{cid}' not found in chunk store")
                continue
            shared = sorted(compute_overlap(query, content))
            if len(shared) > max_overlap:
                failures.append(
                    f"{qid} ({cid}): {len(shared)} overlapping content words {shared} > {max_overlap}"
                )
    return len(semantic_queries), failures


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Enforce <= 1 shared content word between semantic queries and gold chunks."
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=REPO_ROOT / "data" / "evaluation" / "queries_v2.jsonl",
        help="Path to queries_v2.jsonl",
    )
    parser.add_argument(
        "--max-overlap",
        type=int,
        default=1,
        help="Maximum allowed overlapping content words (default: 1)",
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Read v2 corpus chunk text in-memory without connecting to PostgreSQL",
    )
    parser.add_argument("--db-url", default=None, help="PostgreSQL connection URL override")
    args = parser.parse_args()

    checked, failures = verify_semantic_overlap(
        queries_path=args.queries,
        max_overlap=args.max_overlap,
        offline=args.offline,
        db_url=args.db_url,
    )
    if failures:
        print(f"FAILED semantic overlap check ({len(failures)} violations across {checked} queries):")
        for msg in failures:
            print(f"  - {msg}")
        return 1

    print(f"PASS: All {checked} semantic queries share <= {args.max_overlap} content word with every gold chunk.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
