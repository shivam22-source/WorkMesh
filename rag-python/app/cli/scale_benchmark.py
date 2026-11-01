"""Scale benchmark runner evaluating WorkMesh over a 10,000-chunk corpus in PostgreSQL."""

import argparse
import json
import logging
import math
import os
import random
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

import psycopg
from pgvector.psycopg import register_vector

from app.common.config import get_settings
from app.embeddings.mock_provider import MockEmbeddingProvider
from app.indexing.repository import PostgresKnowledgeRepository
from app.retrieval.hybrid import HybridRetriever

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger("cli.scale_benchmark")

# Default connection candidates
CANDIDATE_URLS = [
    "postgresql://knowledge:local_dev_only_change_me@172.19.63.124:5432/knowledge",
    "postgresql://knowledge:local_dev_only_change_me@localhost:5432/knowledge",
]


def resolve_postgres_url(custom_url: Optional[str] = None) -> str:
    """Resolve reachable live PostgreSQL database URL."""
    if custom_url:
        return custom_url
    for url in CANDIDATE_URLS:
        try:
            with psycopg.connect(url, connect_timeout=1) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1;")
                    return url
        except Exception:
            continue
    settings = get_settings()
    return settings.database_url


TOPICS = [
    {
        "category": "payment_validation",
        "keywords": ["payment", "validation", "card verification", "NullPointerException", "HTTP 400"],
        "title_template": "Fix null verification in payment card validation ({ticket})",
        "body_template": (
            "Resolves ticket {ticket}: empty verification payloads were throwing NullPointerException "
            "during checkout. Updated PaymentValidationService to validate card tokens defensively and "
            "return HTTP 400 Bad Request instead of HTTP 500 crash."
        ),
    },
    {
        "category": "db_connection_pool",
        "keywords": ["database", "connection pool", "HikariCP", "timeout", "leak detection"],
        "title_template": "Tune HikariCP connection pool settings for high concurrency ({ticket})",
        "body_template": (
            "Resolves ticket {ticket}: payment service was exhausting connection pool during peak traffic. "
            "Increased maxPoolSize to 50, tuned connectionTimeout to 250ms, and enabled leakDetectionThreshold "
            "at 2000ms to eliminate thread starvation."
        ),
    },
    {
        "category": "jwt_auth_refresh",
        "keywords": ["authentication", "JWT", "refresh token", "session expiry", "OAuth2"],
        "title_template": "Implement silent token refresh with rotation grace period ({ticket})",
        "body_template": (
            "Resolves ticket {ticket}: users were being logged out unexpectedly when tokens expired. "
            "Introduced single-use refresh token rotation with a 30-second grace window to handle concurrent "
            "API requests cleanly."
        ),
    },
    {
        "category": "kafka_backpressure",
        "keywords": ["Kafka", "consumer lag", "partition rebalance", "backpressure", "dead letter queue"],
        "title_template": "Optimize Kafka consumer group commit interval and backpressure ({ticket})",
        "body_template": (
            "Resolves ticket {ticket}: transaction event consumer was experiencing severe lag under burst load. "
            "Switched to manual asynchronous commit and configured a dead letter queue (DLQ) for malformed records."
        ),
    },
    {
        "category": "redis_cache_stampede",
        "keywords": ["Redis", "caching", "cache stampede", "probabilistic early expiration", "TTL"],
        "title_template": "Mitigate cache stampede on employee directory endpoints ({ticket})",
        "body_template": (
            "Resolves ticket {ticket}: database CPU spiked when popular cache keys expired simultaneously. "
            "Implemented XFetch probabilistic early expiration and added jitter to cache TTLs."
        ),
    },
]

SOURCES = ["GITHUB", "SLACK", "EMAIL"]
GROUPS = ["group_engineering", "group_backend", "group_frontend", "group_finance", "group_security"]


def generate_and_seed_scale_corpus(
    db_url: str,
    target_chunks: int = 10000,
    chunks_per_doc: int = 4,
    skip_seed: bool = False,
) -> Tuple[int, int, List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Generate and batch-insert target_chunks into PostgreSQL with HNSW vector index."""
    num_docs = target_chunks // chunks_per_doc
    users = [f"employee_{i:02d}" for i in range(1, 51)]

    labeled_queries: List[Dict[str, Any]] = []
    adversarial_cases: List[Dict[str, Any]] = []

    for d_idx in range(num_docs):
        ticket_id = f"DC-{1000 + d_idx}"
        topic = TOPICS[d_idx % len(TOPICS)]
        source = SOURCES[d_idx % len(SOURCES)]
        author = users[d_idx % len(users)]

        if source == "GITHUB":
            url = f"https://github.com/company/payment-service/pull/{1000 + d_idx}"
        elif source == "SLACK":
            url = f"https://company.slack.com/archives/C0123PAY/p1697{d_idx:08d}"
        else:
            url = f"https://mail.company.internal/mail/{author}/inbox/msg-{1000 + d_idx}"

        title = topic["title_template"].format(ticket=ticket_id)

        acl_category = d_idx % 10
        if acl_category < 6:
            assigned_group = "group_engineering"
            assigned_user = None
            is_restricted = False
        elif acl_category < 8:
            assigned_group = "group_finance"
            assigned_user = None
            is_restricted = True
        elif acl_category < 9:
            assigned_group = "group_security"
            assigned_user = None
            is_restricted = True
        else:
            assigned_group = None
            assigned_user = author
            is_restricted = True

        if d_idx < 100:
            labeled_queries.append({
                "ticket": ticket_id,
                "query": ticket_id,
                "semantic_query": f"how to fix {topic['keywords'][0]} in {ticket_id}",
                "expected_url": url,
                "author": author,
                "assigned_group": assigned_group,
                "assigned_user": assigned_user,
                "is_restricted": is_restricted,
            })

        if is_restricted:
            adversarial_cases.append({
                "ticket": ticket_id,
                "query": title,
                "expected_url": url,
                "assigned_group": assigned_group,
                "assigned_user": assigned_user,
            })

    if skip_seed:
        logger.info("skip_seed_enabled using existing %d chunks in database", target_chunks)
        return num_docs, target_chunks, labeled_queries, adversarial_cases

    logger.info("generating_synthetic_corpus docs=%d chunks=%d", num_docs, target_chunks)

    embedder = MockEmbeddingProvider()

    conn = psycopg.connect(db_url)
    register_vector(conn)

    # 1. Ensure seed users and groups exist
    with conn.cursor() as cur:
        for u in users:
            cur.execute(
                "INSERT INTO users (id, email, full_name, role) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;",
                (u, f"{u}@company.internal", f"Simulated User {u}", "ENGINEER"),
            )
        for g in GROUPS:
            cur.execute(
                "INSERT INTO groups (id, name, description) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING;",
                (g, g.replace("_", " ").title(), f"Simulated group {g}"),
            )
        # Assign memberships
        for i, u in enumerate(users):
            cur.execute(
                "INSERT INTO user_group_membership (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                (u, "group_engineering"),
            )
            if i % 5 == 0:
                cur.execute(
                    "INSERT INTO user_group_membership (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                    (u, "group_finance"),
                )
            if i % 4 == 0:
                cur.execute(
                    "INSERT INTO user_group_membership (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                    (u, "group_security"),
                )

        # Clear existing scale documents to allow clean idempotent reruns
        cur.execute("DELETE FROM documents WHERE id LIKE 'scale:%';")
        cur.execute("DELETE FROM source_records WHERE id LIKE 'scale:%';")
        cur.execute("DELETE FROM acl_references WHERE resource_id LIKE 'scale:%';")
        conn.commit()

    logger.info("seeding_database_records target_chunks=%d", target_chunks)
    random.seed(42)

    source_records_batch = []
    documents_batch = []
    chunks_batch = []
    acls_batch = []
    texts_to_embed = []
    chunk_metas = []

    for d_idx in range(num_docs):
        ticket_id = f"DC-{1000 + d_idx}"
        topic = TOPICS[d_idx % len(TOPICS)]
        source = SOURCES[d_idx % len(SOURCES)]
        author = users[d_idx % len(users)]

        doc_id = f"scale:doc:{d_idx:05d}"
        source_rec_id = f"scale:src:{d_idx:05d}"

        if source == "GITHUB":
            url = f"https://github.com/company/payment-service/pull/{1000 + d_idx}"
        elif source == "SLACK":
            url = f"https://company.slack.com/archives/C0123PAY/p1697{d_idx:08d}"
        else:
            url = f"https://mail.company.internal/mail/{author}/inbox/msg-{1000 + d_idx}"

        title = topic["title_template"].format(ticket=ticket_id)
        base_body = topic["body_template"].format(ticket=ticket_id)

        acl_category = d_idx % 10
        if acl_category < 6:
            assigned_group = "group_engineering"
            assigned_user = None
        elif acl_category < 8:
            assigned_group = "group_finance"
            assigned_user = None
        elif acl_category < 9:
            assigned_group = "group_security"
            assigned_user = None
        else:
            assigned_group = None
            assigned_user = author

        source_records_batch.append((
            source_rec_id, source, f"item-{d_idx}", url, title, author, base_body, "{}", 1
        ))
        documents_batch.append((
            doc_id, source_rec_id, source, title, base_body, author, url, "{}"
        ))

        if assigned_group:
            acls_batch.append(("DOCUMENT", doc_id, "GROUP", assigned_group, "READ"))
        if assigned_user:
            acls_batch.append(("DOCUMENT", doc_id, "USER", assigned_user, "READ"))

        for c_idx in range(chunks_per_doc):
            chunk_id = f"{doc_id}:c{c_idx}"
            chunk_content = (
                f"[{source}] {title}\n"
                f"Section {c_idx + 1}: {base_body} "
                f"Detailed technical notes on {topic['keywords'][c_idx % len(topic['keywords'])]}. "
                f"Trace reference: {ticket_id}."
            )
            texts_to_embed.append(chunk_content)
            chunk_metas.append((chunk_id, doc_id, c_idx, chunk_content, len(chunk_content.split())))

            if assigned_group:
                acls_batch.append(("CHUNK", chunk_id, "GROUP", assigned_group, "READ"))
            if assigned_user:
                acls_batch.append(("CHUNK", chunk_id, "USER", assigned_user, "READ"))

        # Save query benchmark cases for sampling
        if d_idx < 100:
            labeled_queries.append({
                "ticket": ticket_id,
                "query": ticket_id,
                "semantic_query": f"how to fix {topic['keywords'][0]} in {ticket_id}",
                "expected_url": url,
                "author": author,
                "assigned_group": assigned_group,
                "assigned_user": assigned_user,
                "is_restricted": is_restricted,
            })

        if is_restricted:
            adversarial_cases.append({
                "ticket": ticket_id,
                "query": title,
                "expected_url": url,
                "assigned_group": assigned_group,
                "assigned_user": assigned_user,
            })

    # Embed all chunks in fast vectorized batches
    logger.info("computing_embeddings total_chunks=%d", len(texts_to_embed))
    t_emb = time.perf_counter()
    embeddings = embedder.embed_texts(texts_to_embed)
    logger.info("computed_embeddings_completed elapsed=%.2fs", time.perf_counter() - t_emb)

    for (c_id, d_id, c_idx, c_content, token_count), emb in zip(chunk_metas, embeddings):
        chunks_batch.append((c_id, d_id, c_idx, c_content, token_count, emb, "{}"))

    # Batch Insert into PostgreSQL
    logger.info("executing_bulk_insert_into_postgres chunks=%d", len(chunks_batch))
    t_ins = time.perf_counter()
    with conn.cursor() as cur:
        # 1. Source records
        cur.executemany(
            """INSERT INTO source_records (id, source_type, source_id, source_url, title, author_id, raw_content, metadata, version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s) ON CONFLICT DO NOTHING;""",
            source_records_batch,
        )
        # 2. Documents
        cur.executemany(
            """INSERT INTO documents (id, source_record_id, source_type, title, content, author, url, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT DO NOTHING;""",
            documents_batch,
        )
        # 3. Chunks with vector embeddings
        cur.executemany(
            """INSERT INTO chunks (id, document_id, chunk_index, content, token_count, embedding, metadata)
               VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT DO NOTHING;""",
            chunks_batch,
        )
        # 4. ACL references
        cur.executemany(
            """INSERT INTO acl_references (resource_type, resource_id, principal_type, principal_id, permission)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING;""",
            acls_batch,
        )
        conn.commit()

    logger.info("bulk_insert_completed elapsed=%.2fs", time.perf_counter() - t_ins)
    conn.close()

    return num_docs, len(chunks_batch), labeled_queries, adversarial_cases


def run_scale_evaluation(
    db_url: str,
    labeled_queries: List[Dict[str, Any]],
    adversarial_cases: List[Dict[str, Any]],
    num_queries: int = 100,
    num_adversarial_tests: int = 500,
) -> Dict[str, Any]:
    """Execute hybrid retrieval over 10,000 chunks, measuring Recall@K, MRR, latency, and permission isolation."""
    repo = PostgresKnowledgeRepository(connection_url=db_url)
    retriever = HybridRetriever(repository=repo)

    logger.info("running_evaluation_suite queries=%d adversarial_tests=%d", num_queries, num_adversarial_tests)

    # 1. Benchmark Search Queries (Exact Identifier + Semantic Rationale)
    eval_samples = labeled_queries[:num_queries]

    hits_at_1 = 0
    hits_at_3 = 0
    hits_at_5 = 0
    hits_at_10 = 0
    reciprocal_ranks = []
    latencies_ms = []

    for idx, case in enumerate(eval_samples):
        # 50% exact identifier queries, 50% semantic rationale queries
        query_text = case["ticket"] if idx % 2 == 0 else case["semantic_query"]

        # Run as authorized user
        user_id = case["assigned_user"] or "employee_42"
        group_ids = [case["assigned_group"]] if case["assigned_group"] else ["group_engineering"]

        t0 = time.perf_counter()
        results = retriever.search(
            query=query_text,
            limit=10,
            user_id=user_id,
            group_ids=group_ids,
        )
        latency_ms = (time.perf_counter() - t0) * 1000.0
        latencies_ms.append(latency_ms)

        expected_url = case["expected_url"]
        rank = 0
        for r_idx, item in enumerate(results):
            if expected_url in (item.source_url or "") or case["ticket"] in (item.snippet or ""):
                rank = r_idx + 1
                break

        if rank == 1:
            hits_at_1 += 1
        if 0 < rank <= 3:
            hits_at_3 += 1
        if 0 < rank <= 5:
            hits_at_5 += 1
        if 0 < rank <= 10:
            hits_at_10 += 1

        reciprocal_ranks.append(1.0 / rank if rank > 0 else 0.0)

    total_q = len(eval_samples) or 1
    recall_at_1 = (hits_at_1 / total_q) * 100.0
    recall_at_3 = (hits_at_3 / total_q) * 100.0
    recall_at_5 = (hits_at_5 / total_q) * 100.0
    recall_at_10 = (hits_at_10 / total_q) * 100.0
    mrr = sum(reciprocal_ranks) / total_q

    # Compute latency percentiles
    latencies_sorted = sorted(latencies_ms)
    p50 = latencies_sorted[int(0.50 * len(latencies_sorted))]
    p90 = latencies_sorted[int(0.90 * len(latencies_sorted))]
    p95 = latencies_sorted[int(0.95 * len(latencies_sorted))]
    p99 = latencies_sorted[int(0.99 * len(latencies_sorted))]
    mean_latency = sum(latencies_ms) / len(latencies_ms)

    # 2. Adversarial Security / Permission Leakage Test
    logger.info("running_adversarial_security_tests count=%d", num_adversarial_tests)
    leak_count = 0
    adversarial_sample = adversarial_cases * (num_adversarial_tests // len(adversarial_cases) + 1)
    adversarial_sample = adversarial_sample[:num_adversarial_tests]

    unauthorized_user = "unauthorized_attacker_99"
    unauthorized_groups = ["group_unprivileged"]

    for case in adversarial_sample:
        # Attempt to search restricted document content using unauthorized identity
        results = retriever.search(
            query=case["query"],
            limit=10,
            user_id=unauthorized_user,
            group_ids=unauthorized_groups,
        )
        for r in results:
            if case["expected_url"] in (r.source_url or "") or case["ticket"] in (r.snippet or ""):
                leak_count += 1
                break

    leak_rate = (leak_count / len(adversarial_sample)) * 100.0

    return {
        "total_queries": total_q,
        "recall_at_1": round(recall_at_1, 2),
        "recall_at_3": round(recall_at_3, 2),
        "recall_at_5": round(recall_at_5, 2),
        "recall_at_10": round(recall_at_10, 2),
        "mrr": round(mrr, 4),
        "adversarial_tests_run": len(adversarial_sample),
        "permission_leaks_detected": leak_count,
        "permission_leak_rate": round(leak_rate, 4),
        "latency_p50_ms": round(p50, 2),
        "latency_p90_ms": round(p90, 2),
        "latency_p95_ms": round(p95, 2),
        "latency_p99_ms": round(p99, 2),
        "latency_mean_ms": round(mean_latency, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="WorkMesh 10,000-Chunk Scale Benchmark")
    parser.add_argument("--chunks", type=int, default=10000, help="Target total chunks to generate (default: 10000)")
    parser.add_argument("--queries", type=int, default=100, help="Number of evaluation queries (default: 100)")
    parser.add_argument(
        "--adversarial-tests", type=int, default=500, help="Number of adversarial permission tests (default: 500)"
    )
    parser.add_argument("--db-url", type=str, default=None, help="PostgreSQL connection string")
    parser.add_argument("--skip-seed", action="store_true", help="Skip re-seeding if corpus is already in database")
    parser.add_argument("--json", action="store_true", help="Output summary as JSON")

    args = parser.parse_args()
    db_url = resolve_postgres_url(args.db_url)

    logger.info("connecting_to_database url=%s", db_url.split("@")[-1])

    # 1. Generate and seed 10,000 chunks
    t_start = time.perf_counter()
    docs_count, chunks_count, labeled_queries, adversarial_cases = generate_and_seed_scale_corpus(
        db_url=db_url,
        target_chunks=args.chunks,
        skip_seed=args.skip_seed,
    )

    # 2. Run scale evaluation benchmark
    results = run_scale_evaluation(
        db_url=db_url,
        labeled_queries=labeled_queries,
        adversarial_cases=adversarial_cases,
        num_queries=args.queries,
        num_adversarial_tests=args.adversarial_tests,
    )
    total_time = time.perf_counter() - t_start

    if args.json:
        results["total_chunks"] = chunks_count
        results["total_documents"] = docs_count
        results["total_execution_seconds"] = round(total_time, 2)
        print(json.dumps(results, indent=2))
        return

    print("\n" + "=" * 70)
    print("      WORKMESH 10,000-CHUNK SCALE BENCHMARK & SECURITY REPORT")
    print("=" * 70)
    print(f"Corpus Scale:                  {chunks_count:,} chunks ({docs_count:,} documents)")
    print(f"Simulated Multi-Tenant Scope:  50 users, 5 departments across 3 systems")
    print(f"Index Strategy:                pgvector HNSW (cosine) + PostgreSQL GIN (tsvector)")
    print("-" * 70)
    print(f"Evaluated Search Queries:      {results['total_queries']}")
    print(f"Recall@1:                      {results['recall_at_1']}%")
    print(f"Recall@3:                      {results['recall_at_3']}%")
    print(f"Recall@5:                      {results['recall_at_5']}%")
    print(f"Recall@10:                     {results['recall_at_10']}%")
    print(f"Mean Reciprocal Rank (MRR):    {results['mrr']}")
    print("-" * 70)
    print(f"Adversarial Security Tests:    {results['adversarial_tests_run']} cross-tenant queries")
    print(f"Permission Leaks Detected:     {results['permission_leaks_detected']}  (target: 0)")
    print(f"Permission Leak Rate:          {results['permission_leak_rate']}%")
    print("-" * 70)
    print(f"Retrieval Latency (p50):       {results['latency_p50_ms']} ms")
    print(f"Retrieval Latency (p90):       {results['latency_p90_ms']} ms")
    print(f"Retrieval Latency (p95):       {results['latency_p95_ms']} ms")
    print(f"Retrieval Latency (p99):       {results['latency_p99_ms']} ms")
    print(f"Mean Retrieval Latency:        {results['latency_mean_ms']} ms")
    print("=" * 70)
    print(f"Benchmark completed in {total_time:.1f} seconds.\n")


if __name__ == "__main__":
    main()
