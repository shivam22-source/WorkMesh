"""Seed the 10,000-chunk corpus (if needed) and capture EXPLAIN (ANALYZE, BUFFERS) plans.

Executes the exact SQL statements used by WorkMesh's hybrid search pipeline:
1. Lexical retrieval stage (`tsvector` GIN index + pushdown ACL filter)
2. Vector HNSW candidate stage (`hnsw.ef_search=100`, `hnsw.iterative_scan='relaxed_order'`)
3. Adaptive low-access exact/iterative-scan fallback query
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
RAG_PYTHON_DIR = REPO_ROOT / "rag-python"
if str(RAG_PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(RAG_PYTHON_DIR))

import psycopg  # noqa: E402
from pgvector import Vector  # noqa: E402
from pgvector.psycopg import register_vector  # noqa: E402

from app.cli.scale_benchmark import (  # noqa: E402
    generate_and_seed_scale_corpus,
    resolve_postgres_url,
)
from app.embeddings.factory import get_embedding_provider  # noqa: E402
from app.security.acl import build_acl_where_clause  # noqa: E402


def _ensure_corpus_and_indexes(db_url: str, target_chunks: int, reseed: bool) -> int:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM chunks WHERE id LIKE 'scale:%';")
            existing_scale_chunks = int(cur.fetchone()[0])

    if reseed or existing_scale_chunks < target_chunks:
        embedder = get_embedding_provider()
        generate_and_seed_scale_corpus(
            db_url=db_url,
            target_chunks=target_chunks,
            chunks_per_doc=4,
            skip_seed=False,
            embedder=embedder,
        )

    with psycopg.connect(db_url, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw "
                "ON chunks USING hnsw (embedding vector_cosine_ops);"
            )
            cur.execute("ANALYZE chunks;")
            cur.execute("ANALYZE documents;")
            cur.execute("ANALYZE acl_references;")
            cur.execute("SELECT COUNT(*) FROM chunks;")
            return int(cur.fetchone()[0])


def _explain(cur: psycopg.Cursor[Any], sql: str, params: Tuple[Any, ...]) -> str:
    cur.execute(f"EXPLAIN (ANALYZE, BUFFERS)\n{sql}", params)
    return "\n".join(row[0] for row in cur.fetchall())


def capture_plans(
    db_url: str,
    query_text: str = "payment card verification",
    limit: int = 10,
    user_id: str = "employee_42",
    group_ids: List[str] | None = None,
) -> dict[str, str]:
    groups = group_ids if group_ids is not None else ["group_engineering", "group_backend"]
    embedder = get_embedding_provider()
    query_vec = Vector(embedder.embed_texts([query_text])[0])

    acl_clause, acl_params = build_acl_where_clause(
        user_id=user_id,
        group_ids=groups,
        doc_alias="d",
        chunk_alias="c",
        acl_alias="a",
    )

    lexical_sql = f"""
        SELECT
            c.id,
            c.document_id,
            d.source_type,
            COALESCE(d.title, ''),
            c.content,
            COALESCE(d.url, ''),
            d.author,
            ts_rank_cd(c.tsv, plainto_tsquery('english', %s)) AS score
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE c.tsv @@ plainto_tsquery('english', %s)
          AND {acl_clause}
        ORDER BY score DESC, c.created_at DESC
        LIMIT %s
    """
    lexical_params = (query_text, query_text, *acl_params, limit)

    candidate_k = max(100, limit * 10)
    hnsw_candidate_sql = f"""
        WITH candidates AS (
            SELECT
                c.id,
                c.document_id,
                c.content,
                (c.embedding <=> %s) AS dist
            FROM chunks c
            WHERE c.embedding IS NOT NULL AND (- (c.embedding <#> c.embedding)) > 0
            ORDER BY c.embedding <=> %s ASC
            LIMIT %s
        )
        SELECT
            c.id,
            c.document_id,
            d.source_type,
            COALESCE(d.title, ''),
            c.content,
            COALESCE(d.url, ''),
            d.author,
            ROUND((1 - c.dist)::numeric, 4) AS score
        FROM candidates c
        JOIN documents d ON c.document_id = d.id
        WHERE {acl_clause}
        ORDER BY c.dist ASC
        LIMIT %s
    """
    hnsw_params = (query_vec, query_vec, candidate_k, *acl_params, limit)

    low_acl_clause, low_acl_params = build_acl_where_clause(
        user_id="employee_01",
        group_ids=[],
        doc_alias="d",
        chunk_alias="c",
        acl_alias="a",
    )
    fallback_sql = f"""
        SELECT
            c.id,
            c.document_id,
            d.source_type,
            COALESCE(d.title, ''),
            c.content,
            COALESCE(d.url, ''),
            d.author,
            ROUND((1 - (c.embedding <=> %s))::numeric, 4) AS score
        FROM chunks c
        JOIN documents d ON c.document_id = d.id
        WHERE c.embedding IS NOT NULL AND (- (c.embedding <#> c.embedding)) > 0
          AND {low_acl_clause}
        ORDER BY c.embedding <=> %s ASC
        LIMIT %s
    """
    fallback_params = (query_vec, *low_acl_params, query_vec, limit)

    with psycopg.connect(db_url) as conn:
        register_vector(conn)
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute("SET LOCAL hnsw.ef_search = 100;")
                cur.execute("SET LOCAL hnsw.iterative_scan = 'relaxed_order';")
                return {
                    "lexical": _explain(cur, lexical_sql, lexical_params),
                    "hnsw_candidate": _explain(cur, hnsw_candidate_sql, hnsw_params),
                    "low_access_fallback": _explain(cur, fallback_sql, fallback_params),
                }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed 10k-chunk corpus if missing and print EXPLAIN (ANALYZE, BUFFERS) plans."
    )
    parser.add_argument("--db-url", default=None, help="PostgreSQL connection string override.")
    parser.add_argument("--chunks", type=int, default=10000, help="Target scale chunk count (default: 10000).")
    parser.add_argument("--reseed", action="store_true", help="Force re-seeding the scale corpus.")
    parser.add_argument("--query", default="payment card verification", help="Sample query text.")
    parser.add_argument("--limit", type=int, default=10, help="Result limit per query.")
    args = parser.parse_args()

    db_url = resolve_postgres_url(args.db_url)
    total_chunks = _ensure_corpus_and_indexes(db_url, target_chunks=args.chunks, reseed=args.reseed)
    plans = capture_plans(db_url=db_url, query_text=args.query, limit=args.limit)

    print(f"Total chunks in database: {total_chunks}\n")
    for name, plan in plans.items():
        print(f"=== {name.upper()} ===")
        print(plan)
        print()


if __name__ == "__main__":
    main()
