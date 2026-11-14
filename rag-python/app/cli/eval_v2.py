"""Evaluate WorkMesh retrieval strategies against data/evaluation/queries_v2.jsonl.

Computes Recall@1, Recall@3, Recall@5, Recall@10, MRR, and nDCG@10 with bootstrap
95% confidence intervals across all 60 queries and each 20-query category
(exact_identifier, semantic, multi_source), plus paired bootstrap deltas.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import psycopg

from app.cli.scale_benchmark import resolve_postgres_url
from app.embeddings.factory import get_embedding_provider
from app.evaluation.corpus_v2 import seed_v2_evaluation_corpus
from app.evaluation.metrics import (
    aggregate_query_metrics,
    evaluate_query_ranking,
    paired_bootstrap_delta_ci,
)
from app.indexing.repository import PostgresKnowledgeRepository
from app.rag.cross_encoder_reranker import CrossEncoderReranker
from app.rag.reranker import DeterministicReranker
from app.retrieval.hybrid import HybridRetriever

logging.basicConfig(
    level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","message":"%(message)s"}',
)
logger = logging.getLogger("cli.eval_v2")

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_QUERIES_PATH = REPO_ROOT / "data" / "evaluation" / "queries_v2.jsonl"
DEFAULT_OUTPUT_PATH = REPO_ROOT / "data" / "evaluation" / "results" / "ablation_v2_results.json"


def load_queries_v2(path: Path = DEFAULT_QUERIES_PATH) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped:
                records.append(json.loads(stripped))
    return records


def ensure_v2_seeded(db_url: str, reseed: bool = False) -> None:
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM documents WHERE metadata->>'eval_v2' = 'true';")
            count = int(cur.fetchone()[0])
    if reseed or count < 75:
        logger.info("seeding_v2_corpus existing_docs=%d reseed=%s", count, reseed)
        seed_v2_evaluation_corpus(db_url)


def _format_pct_ci(metric_dict: Dict[str, float]) -> str:
    return (
        f"{metric_dict['mean'] * 100:.1f}% "
        f"[{metric_dict['ci_low'] * 100:.1f}%, {metric_dict['ci_high'] * 100:.1f}%]"
    )


def _format_val_ci(metric_dict: Dict[str, float]) -> str:
    return f"{metric_dict['mean']:.4f} [{metric_dict['ci_low']:.4f}, {metric_dict['ci_high']:.4f}]"


def evaluate_queries_v2(
    db_url: str,
    queries: List[Dict[str, Any]],
    *,
    limit: int = 10,
    graph_candidate_pool: int = 20,
    include_cross_encoder: bool = False,
    n_resamples: int = 2000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Run lexical, vector, hybrid, hybrid+graph, and optional cross-encoder over queries_v2."""
    repo = PostgresKnowledgeRepository(connection_url=db_url)
    embedder = get_embedding_provider()
    embedder.embed_texts(["warmup query"])
    retriever = HybridRetriever(repository=repo, embedding_provider=embedder)
    reranker = DeterministicReranker(repository=repo)

    ce_retriever: Optional[HybridRetriever] = None
    if include_cross_encoder:
        ce_reranker = CrossEncoderReranker(top_k=50)
        # Warm up CrossEncoder weights once before per-query latency measurement
        ce_reranker._get_model().predict([("warmup query", "warmup passage")])
        ce_retriever = HybridRetriever(
            repository=repo,
            embedding_provider=embedder,
            cross_encoder_reranker=ce_reranker,
        )

    strat_keys = ["lexical_only", "lexical_and", "vector_only", "hybrid_rrf", "hybrid_plus_graph"]
    if include_cross_encoder:
        strat_keys.append("hybrid_cross_encoder")
    per_strategy_rows: Dict[str, List[Dict[str, Any]]] = {k: [] for k in strat_keys}
    categories = tuple(sorted(list({q["category"] for q in queries})))
    per_strategy_by_cat: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        k: {c: [] for c in categories} for k in strat_keys
    }

    for q in queries:
        query_text = q["query"]
        user_id = q["user_id"]
        group_ids = q["group_ids"]
        qrels = q["qrels"]
        category = q["category"]

        # 1a. Lexical only (Fair OR semantics / ts_rank_cd)
        t0 = time.perf_counter()
        lex_or_hits = retriever.lexical_retriever.search(
            query=query_text, limit=limit, user_id=user_id, group_ids=group_ids, semantics="or"
        )
        lex_or_ms = (time.perf_counter() - t0) * 1000.0

        # 1b. Lexical (AND) strict (for transparency)
        t0 = time.perf_counter()
        lex_and_hits = retriever.lexical_retriever.search(
            query=query_text, limit=limit, user_id=user_id, group_ids=group_ids, semantics="and"
        )
        lex_and_ms = (time.perf_counter() - t0) * 1000.0

        # 2. Vector only
        t0 = time.perf_counter()
        vec_hits = retriever.vector_retriever.search(
            query=query_text, limit=limit, user_id=user_id, group_ids=group_ids
        )
        vec_ms = (time.perf_counter() - t0) * 1000.0

        # 3. Hybrid RRF baseline and 4. Hybrid + Graph boost on the exact same candidate pool
        t0 = time.perf_counter()
        hyb_pool = retriever.search(
            query=query_text, limit=graph_candidate_pool, user_id=user_id, group_ids=group_ids
        )
        hyb_ms = (time.perf_counter() - t0) * 1000.0
        hyb_hits = hyb_pool[:limit]

        t0 = time.perf_counter()
        hyb_pool_for_graph = retriever.search(
            query=query_text, limit=graph_candidate_pool, user_id=user_id, group_ids=group_ids
        )
        graph_hits = reranker.rerank(
            query=query_text, candidates=hyb_pool_for_graph, user_id=user_id, group_ids=group_ids
        )[:limit]
        graph_ms = (time.perf_counter() - t0) * 1000.0

        runs = {
            "lexical_only": (lex_or_hits, lex_or_ms),
            "lexical_and": (lex_and_hits, lex_and_ms),
            "vector_only": (vec_hits, vec_ms),
            "hybrid_rrf": (hyb_hits, hyb_ms),
            "hybrid_plus_graph": (graph_hits, graph_ms),
        }

        if ce_retriever is not None:
            t0 = time.perf_counter()
            ce_hits = ce_retriever.search(
                query=query_text, limit=limit, user_id=user_id, group_ids=group_ids
            )
            ce_ms = (time.perf_counter() - t0) * 1000.0
            runs["hybrid_cross_encoder"] = (ce_hits, ce_ms)

        for key, (items, ms) in runs.items():
            row = evaluate_query_ranking([c.chunk_id for c in items], qrels, latency_ms=ms)
            row["id"] = q["id"]
            row["category"] = category
            per_strategy_rows[key].append(row)
            per_strategy_by_cat[key][category].append(row)

    results: Dict[str, Any] = {
        "dataset": "data/evaluation/queries_v2.jsonl",
        "total_queries": len(queries),
        "bootstrap_resamples": n_resamples,
        "confidence_level": 0.95,
        "strategies": {},
        "paired_comparisons": {},
    }

    for key in strat_keys:
        overall = aggregate_query_metrics(per_strategy_rows[key], n_resamples=n_resamples, seed=seed)
        by_cat = {
            cat: aggregate_query_metrics(per_strategy_by_cat[key][cat], n_resamples=n_resamples, seed=seed)
            for cat in categories
        }
        strat_dict: Dict[str, Any] = {
            "overall": overall,
            "by_category": by_cat,
        }
        dev_rows = [
            r for r in per_strategy_rows[key] if r["category"] in ("exact_identifier", "semantic", "multi_source")
        ]
        if len(dev_rows) == 60:
            strat_dict["dev_60"] = aggregate_query_metrics(dev_rows, n_resamples=n_resamples, seed=seed)

        denied_rows = [r for r in per_strategy_rows[key] if r["category"] == "denied_identity"]
        if denied_rows:
            leaks = sum(1 for r in denied_rows if r["recall_at_10"] > 0)
            strat_dict["denied_identity_leaks"] = leaks
            strat_dict["denied_identity_leak_rate"] = leaks / len(denied_rows)

        results["strategies"][key] = strat_dict

    # Paired bootstrap checks
    comparisons = [
        ("hybrid_plus_graph", "hybrid_plus_graph_vs_hybrid"),
    ]
    if include_cross_encoder:
        comparisons.append(("hybrid_cross_encoder", "hybrid_cross_encoder_vs_hybrid"))

    for cand_key, prefix in comparisons:
        for scope_name, cat_filter in (("overall", None), ("multi_source", "multi_source"), ("semantic", "semantic")):
            base_rows = [
                r for r in per_strategy_rows["hybrid_rrf"] if cat_filter is None or r["category"] == cat_filter
            ]
            cand_rows = [
                r for r in per_strategy_rows[cand_key] if cat_filter is None or r["category"] == cat_filter
            ]
            results["paired_comparisons"][f"{prefix}_{scope_name}"] = {
                metric: paired_bootstrap_delta_ci(
                    [r[metric] for r in base_rows],
                    [r[metric] for r in cand_rows],
                    n_resamples=n_resamples,
                    seed=seed,
                )
                for metric in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
            }

    return results


def print_ablation_report(results: Dict[str, Any]) -> None:
    total_q = results.get("total_queries", 0)
    print("\n" + "=" * 96)
    print(f"WORKMESH v2 GRADED EVALUATION ({total_q} queries evaluated)")
    print("=" * 96)

    first_strat = next(iter(results["strategies"].values()))
    has_dev_60 = "dev_60" in first_strat

    if has_dev_60:
        print("\n--- DEV SET (60 Queries Tuned Baseline) ---")
        header = (
            f"{'Strategy':<22} | {'R@1':<18} | {'R@5 [95% CI]':<22} | "
            f"{'MRR [95% CI]':<22} | {'nDCG@10 [95% CI]':<22} | {'p50/p95 ms'}"
        )
        print(header)
        print("-" * 96)
        for strat_key, data in results["strategies"].items():
            dev = data["dev_60"]
            print(
                f"{strat_key:<22} | "
                f"{dev['recall_at_1']['mean']*100:>5.1f}%            | "
                f"{_format_pct_ci(dev['recall_at_5']):<22} | "
                f"{_format_val_ci(dev['mrr']):<22} | "
                f"{_format_val_ci(dev['ndcg_at_10']):<22} | "
                f"{dev['latency_ms']['p50']:.1f}/{dev['latency_ms']['p95']:.1f}"
            )

    print(f"\n--- OVERALL ({total_q} Queries) ---")
    header = (
        f"{'Strategy':<22} | {'R@1':<18} | {'R@5 [95% CI]':<22} | "
        f"{'MRR [95% CI]':<22} | {'nDCG@10 [95% CI]':<22} | {'p50/p95 ms'}"
    )
    print(header)
    print("-" * 96)
    for strat_key, data in results["strategies"].items():
        ov = data["overall"]
        print(
            f"{strat_key:<22} | "
            f"{ov['recall_at_1']['mean']*100:>5.1f}%            | "
            f"{_format_pct_ci(ov['recall_at_5']):<22} | "
            f"{_format_val_ci(ov['mrr']):<22} | "
            f"{_format_val_ci(ov['ndcg_at_10']):<22} | "
            f"{ov['latency_ms']['p50']:.1f}/{ov['latency_ms']['p95']:.1f}"
        )

    print("\n--- Breakdown by Category (nDCG@10 / Recall@5) ---")
    cats = list(first_strat.get("by_category", {}).keys())
    for strat_key, data in results["strategies"].items():
        parts = []
        for cat in cats:
            if cat in data["by_category"]:
                c = data["by_category"][cat]
                parts.append(
                    f"{cat}: R@5={c['recall_at_5']['mean']*100:.1f}%, nDCG@10={c['ndcg_at_10']['mean']:.4f}"
                )
        print(f"  {strat_key:<20} -> " + " | ".join(parts))

    if "denied_identity" in cats:
        print("\n--- Denied-Identity Security Isolation (12 Queries) ---")
        for strat_key, data in results["strategies"].items():
            leaks = data.get("denied_identity_leaks", 0)
            rate = data.get("denied_identity_leak_rate", 0.0)
            print(f"  {strat_key:<20} -> Leaks: {leaks}/12 ({rate*100:.1f}% leak rate)")

    print("\n--- Paired Bootstrap Delta (hybrid_plus_graph - hybrid_rrf) ---")
    for scope, comps in results["paired_comparisons"].items():
        r5 = comps["recall_at_5"]
        ndcg = comps["ndcg_at_10"]
        print(
            f"  {scope:<40} R@5={r5['delta_mean']*100:+.2f}pp [{r5['ci_low']*100:+.2f}, {r5['ci_high']*100:+.2f}] sig={r5['statistically_significant']} | "
            f"nDCG@10={ndcg['delta_mean']:+.4f} [{ndcg['ci_low']:+.4f}, {ndcg['ci_high']:+.4f}] sig={ndcg['statistically_significant']}"
        )
    print("=" * 96 + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Run v2 retrieval ablation benchmark.")
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--queries", type=Path, default=DEFAULT_QUERIES_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--reseed", action="store_true")
    parser.add_argument("--include-cross-encoder", action="store_true")
    parser.add_argument("--bootstrap-resamples", type=int, default=2000)
    args = parser.parse_args()

    db_url = resolve_postgres_url(args.db_url)
    ensure_v2_seeded(db_url, reseed=args.reseed)
    queries = load_queries_v2(args.queries)
    results = evaluate_queries_v2(
        db_url,
        queries,
        include_cross_encoder=args.include_cross_encoder,
        n_resamples=args.bootstrap_resamples,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
    print_ablation_report(results)
    print(f"Saved raw results to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
