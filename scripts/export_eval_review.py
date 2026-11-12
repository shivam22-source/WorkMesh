"""Export queries_v2.jsonl and PostgreSQL gold chunks into a human-reviewable Markdown file."""

from __future__ import annotations

import argparse
import os
import random
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_DIR.parent
RAG_PYTHON_DIR = REPO_ROOT / "rag-python"

for path_entry in (str(RAG_PYTHON_DIR), str(SCRIPTS_DIR)):
    if path_entry not in sys.path:
        sys.path.insert(0, path_entry)

from check_overlap import load_queries_jsonl  # noqa: E402


@dataclass(frozen=True)
class ChunkRecord:
    """Chunk metadata and full text retrieved from PostgreSQL."""

    chunk_id: str
    source: str
    content: str


def _read_env_file(env_path: Path) -> dict[str, str]:
    """Parse simple KEY=VALUE lines from an optional .env file without mutating process env."""
    if not env_path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        values[key.strip()] = val.strip().strip('"').strip("'")
    return values


def _resolve_db_url(custom_url: str | None = None) -> str:
    """Resolve a reachable PostgreSQL URL from CLI flag, environment, rag-python/.env, or defaults."""
    if custom_url:
        return custom_url

    import psycopg

    from app.cli.scale_benchmark import CANDIDATE_URLS

    file_env = {
        **_read_env_file(REPO_ROOT / ".env"),
        **_read_env_file(RAG_PYTHON_DIR / ".env"),
    }

    def get_cfg(key: str, default: str) -> str:
        return os.environ.get(key) or file_env.get(key) or default

    explicit_url = os.environ.get("DATABASE_URL") or file_env.get("DATABASE_URL")
    configured_url = explicit_url or (
        f"postgresql://{get_cfg('POSTGRES_USER', 'ekr')}:{get_cfg('POSTGRES_PASSWORD', 'ekr_password')}"
        f"@{get_cfg('POSTGRES_HOST', 'localhost')}:{get_cfg('POSTGRES_PORT', '5432')}"
        f"/{get_cfg('POSTGRES_DB', 'ekr_db')}"
    )

    for url in [configured_url, *CANDIDATE_URLS]:
        try:
            with psycopg.connect(url, connect_timeout=1) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    return url
        except Exception:
            continue
    return configured_url


def fetch_gold_chunks_from_postgres(
    chunk_ids: Iterable[str],
    db_url: str | None = None,
) -> dict[str, ChunkRecord]:
    """Fetch source type and full chunk text from PostgreSQL for all gold chunk IDs."""
    import psycopg

    ids = sorted(set(chunk_ids))
    if not ids:
        return {}

    dsn = _resolve_db_url(db_url)
    sql = """
        SELECT c.id, LOWER(d.source_type), c.content
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE c.id = ANY(%s);
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(sql, (ids,))
        return {
            row[0]: ChunkRecord(chunk_id=row[0], source=row[1], content=row[2])
            for row in cur.fetchall()
        }


def _safe_fence(text: str) -> str:
    """Return a backtick fence longer than any backtick sequence in text."""
    runs = re.findall(r"`+", text)
    max_len = max((len(r) for r in runs), default=2)
    return "`" * max(3, max_len + 1)


def _format_query_section(record: dict, chunks: dict[str, ChunkRecord]) -> list[str]:
    """Format one query record and all of its gold chunks into Markdown lines."""
    qid = record["id"]
    category = record.get("category", "")
    user_id = record.get("user_id", "")
    group_ids = record.get("group_ids") or []
    identity = f"`{user_id}` (groups: {', '.join(f'`{g}`' for g in group_ids)})"
    query_text = record["query"]
    qrels: dict[str, int] = record.get("qrels", {})

    lines: list[str] = [
        f"### {qid}",
        "",
        f"- **Query ID:** `{qid}`",
        f"- **Query Type:** `{category}`",
        f"- **Identity:** {identity}",
        f"- **Query Text:** {query_text}",
        "",
    ]

    sorted_qrels = sorted(qrels.items(), key=lambda kv: (-int(kv[1]), kv[0]))
    for cid, grade in sorted_qrels:
        chunk = chunks.get(cid)
        if chunk is None:
            raise RuntimeError(f"Gold chunk '{cid}' for query '{qid}' was not found in PostgreSQL.")
        fence = _safe_fence(chunk.content)
        lines.extend([
            f"#### Gold Chunk `{cid}` — grade `{grade}` — source `{chunk.source}`",
            "",
            f"{fence}text",
            chunk.content.rstrip("\n"),
            fence,
            "",
        ])

    return lines


def build_review_markdown(
    records: list[dict],
    chunks: dict[str, ChunkRecord],
    seed: int = 42,
    sample_size: int = 15,
) -> str:
    """Render all evaluation queries with seed-sampled priority review queries first."""
    rng = random.Random(seed)
    count = min(sample_size, len(records))
    sampled = rng.sample(records, count)
    sampled_ids = {r["id"] for r in sampled}
    remaining = [r for r in records if r["id"] not in sampled_ids]

    lines: list[str] = [
        "# Evaluation Set Manual Review (`queries_v2`)",
        "",
        f"Total queries: **{len(records)}** | Priority sample size: **{len(sampled)}** (`seed={seed}`)",
        "",
        "## REVIEW THESE 15",
        "",
    ]
    for record in sampled:
        lines.extend(_format_query_section(record, chunks))

    if remaining:
        lines.extend([
            f"## REMAINING QUERIES ({len(remaining)})",
            "",
        ])
        for record in remaining:
            lines.extend(_format_query_section(record, chunks))

    return "\n".join(lines).rstrip() + "\n"


def export_eval_review(
    queries_path: Path,
    output_path: Path,
    db_url: str | None = None,
    seed: int = 42,
    sample_size: int = 15,
) -> tuple[int, int]:
    """Read queries_v2.jsonl, load gold chunk texts from PostgreSQL, and write review Markdown."""
    records = load_queries_jsonl(queries_path)
    gold_ids = [cid for r in records for cid in r.get("qrels", {}).keys()]
    chunks = fetch_gold_chunks_from_postgres(gold_ids, db_url=db_url)
    markdown = build_review_markdown(records, chunks, seed=seed, sample_size=sample_size)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return len(records), len(chunks)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export queries_v2.jsonl with full DB chunk texts into review_queries_v2.md."
    )
    parser.add_argument(
        "--queries",
        type=Path,
        default=REPO_ROOT / "data" / "evaluation" / "queries_v2.jsonl",
        help="Path to input queries JSONL file",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=REPO_ROOT / "data" / "evaluation" / "review_queries_v2.md",
        help="Path to output Markdown review file",
    )
    parser.add_argument("--db-url", default=None, help="PostgreSQL connection URL override")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for priority sample (default: 42)")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=15,
        help="Number of queries to sample under REVIEW THESE 15 (default: 15)",
    )
    args = parser.parse_args()

    total_queries, total_chunks = export_eval_review(
        queries_path=args.queries,
        output_path=args.output,
        db_url=args.db_url,
        seed=args.seed,
        sample_size=args.sample_size,
    )
    print(f"Exported {total_queries} queries and {total_chunks} gold chunks to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
