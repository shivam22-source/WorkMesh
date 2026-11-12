"""Run systematic parameter sweeps over queries_v2 to diagnose and fix semantic weakness."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from app.cli.eval_v2 import ensure_v2_seeded, load_queries_v2
from app.cli.scale_benchmark import resolve_postgres_url
from app.embeddings.factory import get_embedding_provider
from app.evaluation.metrics import aggregate_query_metrics, evaluate_query_ranking
from app.indexing.repository import PostgresKnowledgeRepository
from app.retrieval.hybrid import HybridRetriever

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SWEEP_OUTPUT = REPO_ROOT / "data" / "evaluation" / "results" / "sweep_v2_results.json"


@dataclass(frozen=True)
class ExperimentConfig:
    name: str
    group: str
    rrf_k: int = 60
    candidate_pool_size: int = 20
    hnsw_ef_search: int = 100
    lexical_weight: float = 1.0
    vector_weight: float = 1.0
    enable_query_routing: bool = False
    routing_weights: Optional[Dict[str, Tuple[float, float]]] = None
    lexical_or_fallback: bool = False


def run_single_experiment(
    db_url: str,
    embedder: Any,
    queries: List[Dict[str, Any]],
    cfg: ExperimentConfig,
    *,
    limit: int = 10,
    n_resamples: int = 1000,
) -> Dict[str, Any]:
    repo = PostgresKnowledgeRepository(
        connection_url=db_url,
        hnsw_ef_search=cfg.hnsw_ef_search,
        lexical_or_fallback=cfg.lexical_or_fallback,
    )
    retriever = HybridRetriever(
        repository=repo,
        embedding_provider=embedder,
        k=cfg.rrf_k,
        lexical_weight=cfg.lexical_weight,
        vector_weight=cfg.vector_weight,
        candidate_pool_size=cfg.candidate_pool_size,
        enable_query_routing=cfg.enable_query_routing,
        routing_weights=cfg.routing_weights,
    )

    categories = ("exact_identifier", "semantic", "multi_source")
    all_rows: List[Dict[str, Any]] = []
    by_cat_rows: Dict[str, List[Dict[str, Any]]] = {c: [] for c in categories}

    for q in queries:
        t0 = time.perf_counter()
        hits = retriever.search(
            query=q["query"],
            limit=limit,
            user_id=q["user_id"],
            group_ids=q["group_ids"],
        )
        ms = (time.perf_counter() - t0) * 1000.0
        row = evaluate_query_ranking([h.chunk_id for h in hits], q["qrels"], latency_ms=ms)
        all_rows.append(row)
        by_cat_rows[q["category"]].append(row)

    return {
        "name": cfg.name,
        "group": cfg.group,
        "params": {
            "rrf_k": cfg.rrf_k,
            "candidate_pool_size": cfg.candidate_pool_size,
            "hnsw_ef_search": cfg.hnsw_ef_search,
            "lexical_weight": cfg.lexical_weight,
            "vector_weight": cfg.vector_weight,
            "enable_query_routing": cfg.enable_query_routing,
            "routing_weights": cfg.routing_weights,
            "lexical_or_fallback": cfg.lexical_or_fallback,
        },
        "overall": aggregate_query_metrics(all_rows, n_resamples=n_resamples, seed=42),
        "by_category": {
            cat: aggregate_query_metrics(by_cat_rows[cat], n_resamples=n_resamples, seed=42)
            for cat in categories
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep HybridRetriever and HNSW parameters on queries_v2.")
    parser.add_argument("--db-url", default=None)
    parser.add_argument("--output", type=Path, default=DEFAULT_SWEEP_OUTPUT)
    args = parser.parse_args()

    db_url = resolve_postgres_url(args.db_url)
    ensure_v2_seeded(db_url)
    queries = load_queries_v2()
    embedder = get_embedding_provider()
    embedder.embed_texts(["warmup query"])

    experiments: List[ExperimentConfig] = [
        # 0. True limit=10 baseline
        ExperimentConfig("baseline_k60_pool20_ef100", "baseline"),
        # 1. Sweep candidate_pool_size (with ef_search=100 vs tuned ef_search)
        ExperimentConfig("pool_40_ef100", "candidate_pool", candidate_pool_size=40, hnsw_ef_search=100),
        ExperimentConfig("pool_80_ef100", "candidate_pool", candidate_pool_size=80, hnsw_ef_search=100),
        ExperimentConfig("pool_120_ef100", "candidate_pool", candidate_pool_size=120, hnsw_ef_search=100),
        # 2. Sweep hnsw.ef_search (diagnosing clustered HNSW local optima)
        ExperimentConfig("ef200_pool20", "hnsw_ef_search", candidate_pool_size=20, hnsw_ef_search=200),
        ExperimentConfig("ef300_pool20", "hnsw_ef_search", candidate_pool_size=20, hnsw_ef_search=300),
        ExperimentConfig("ef400_pool50", "hnsw_ef_search", candidate_pool_size=50, hnsw_ef_search=400),
        # 3. Sweep RRF k at ef300_pool50
        ExperimentConfig("rrf_k10_ef300_p50", "rrf_k", rrf_k=10, candidate_pool_size=50, hnsw_ef_search=300),
        ExperimentConfig("rrf_k20_ef300_p50", "rrf_k", rrf_k=20, candidate_pool_size=50, hnsw_ef_search=300),
        ExperimentConfig("rrf_k40_ef300_p50", "rrf_k", rrf_k=40, candidate_pool_size=50, hnsw_ef_search=300),
        ExperimentConfig("rrf_k60_ef300_p50", "rrf_k", rrf_k=60, candidate_pool_size=50, hnsw_ef_search=300),
        ExperimentConfig("rrf_k100_ef300_p50", "rrf_k", rrf_k=100, candidate_pool_size=50, hnsw_ef_search=300),
        # 4. Static per-retriever weights at k=20, ef300, pool=50
        ExperimentConfig("weights_lex1.5_vec0.5", "weights", rrf_k=20, candidate_pool_size=50, hnsw_ef_search=300, lexical_weight=1.5, vector_weight=0.5),
        ExperimentConfig("weights_lex0.5_vec1.5", "weights", rrf_k=20, candidate_pool_size=50, hnsw_ef_search=300, lexical_weight=0.5, vector_weight=1.5),
        ExperimentConfig("weights_lex0.3_vec1.7", "weights", rrf_k=20, candidate_pool_size=50, hnsw_ef_search=300, lexical_weight=0.3, vector_weight=1.7),
        ExperimentConfig("weights_lex0.0_vec1.0", "weights", rrf_k=20, candidate_pool_size=50, hnsw_ef_search=300, lexical_weight=0.0, vector_weight=1.0),
        # 5. Query-type routing
        ExperimentConfig(
            "routing_balanced_id1.6_sem1.6",
            "routing",
            rrf_k=20,
            candidate_pool_size=50,
            hnsw_ef_search=300,
            enable_query_routing=True,
            routing_weights={"identifier": (1.6, 0.4), "semantic": (0.4, 1.6), "default": (1.0, 1.0)},
        ),
        ExperimentConfig(
            "routing_strong_id1.8_sem1.8",
            "routing",
            rrf_k=20,
            candidate_pool_size=50,
            hnsw_ef_search=300,
            enable_query_routing=True,
            routing_weights={"identifier": (1.8, 0.2), "semantic": (0.2, 1.8), "default": (1.0, 1.0)},
        ),
        ExperimentConfig(
            "routing_id1.6_sem1.6_k60",
            "routing",
            rrf_k=60,
            candidate_pool_size=50,
            hnsw_ef_search=300,
            enable_query_routing=True,
            routing_weights={"identifier": (1.6, 0.4), "semantic": (0.4, 1.6), "default": (1.0, 1.0)},
        ),
        # 6. Lexical OR fallback + Routing
        ExperimentConfig(
            "or_fallback_ef300_p50_noroute",
            "lexical_or_fallback",
            rrf_k=60,
            candidate_pool_size=50,
            hnsw_ef_search=300,
            lexical_or_fallback=True,
        ),
        ExperimentConfig(
            "or_fallback_routing_id1.6_sem1.6",
            "lexical_or_fallback",
            rrf_k=20,
            candidate_pool_size=50,
            hnsw_ef_search=300,
            enable_query_routing=True,
            routing_weights={"identifier": (1.6, 0.4), "semantic": (0.4, 1.6), "default": (1.0, 1.0)},
            lexical_or_fallback=True,
        ),
    ]

    results: List[Dict[str, Any]] = []
    print(f"\n{'Experiment':<30} | {'R@5':>6} | {'nDCG@10':>7} | {'MRR':>6} | {'ID R@5':>6} | {'Sem R@5':>7} | {'Mul R@5':>7} | {'p50/p95 ms'}")
    print("-" * 105)
    for cfg in experiments:
        res = run_single_experiment(db_url, embedder, queries, cfg)
        results.append(res)
        ov = res["overall"]
        cats = res["by_category"]
        print(
            f"{cfg.name:<30} | "
            f"{ov['recall_at_5']['mean']*100:>5.1f}% | "
            f"{ov['ndcg_at_10']['mean']:>7.4f} | "
            f"{ov['mrr']['mean']:>6.4f} | "
            f"{cats['exact_identifier']['recall_at_5']['mean']*100:>5.1f}% | "
            f"{cats['semantic']['recall_at_5']['mean']*100:>6.1f}% | "
            f"{cats['multi_source']['recall_at_5']['mean']*100:>6.1f}% | "
            f"{ov['latency_ms']['p50']:.1f}/{ov['latency_ms']['p95']:.1f}"
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"experiments": results}, indent=2) + "\n", encoding="utf-8")
    print(f"\nSaved sweep results to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
