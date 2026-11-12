"""Standard IR evaluation metrics with graded relevance and bootstrap confidence intervals."""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence


def recall_at_k(ranked_ids: Sequence[str], qrels: Dict[str, int], k: int) -> float:
    """Fraction of relevant items (grade >= 1) retrieved within the top-k results."""
    relevant = {cid for cid, grade in qrels.items() if grade >= 1}
    if not relevant or k <= 0:
        return 0.0
    hits = len(set(ranked_ids[:k]) & relevant)
    return hits / len(relevant)


def reciprocal_rank(
    ranked_ids: Sequence[str],
    qrels: Dict[str, int],
    k: Optional[int] = None,
) -> float:
    """Reciprocal rank of the first relevant item (grade >= 1)."""
    window = ranked_ids[:k] if k is not None else ranked_ids
    for idx, cid in enumerate(window, start=1):
        if qrels.get(cid, 0) >= 1:
            return 1.0 / idx
    return 0.0


def dcg_at_k(ranked_ids: Sequence[str], qrels: Dict[str, int], k: int = 10) -> float:
    """Discounted cumulative gain with exponential relevance gains (2^rel - 1)."""
    dcg = 0.0
    for idx, cid in enumerate(ranked_ids[:k], start=1):
        rel = qrels.get(cid, 0)
        if rel > 0:
            dcg += ((2**rel) - 1) / math.log2(idx + 1)
    return dcg


def ndcg_at_k(ranked_ids: Sequence[str], qrels: Dict[str, int], k: int = 10) -> float:
    """Normalized discounted cumulative gain at rank cutoff k."""
    if k <= 0:
        return 0.0
    ideal_grades = sorted((g for g in qrels.values() if g > 0), reverse=True)[:k]
    if not ideal_grades:
        return 0.0
    idcg = sum(((2**g) - 1) / math.log2(idx + 1) for idx, g in enumerate(ideal_grades, start=1))
    if idcg <= 0.0:
        return 0.0
    return dcg_at_k(ranked_ids, qrels, k=k) / idcg


def percentile(values: Sequence[float], pct: float) -> float:
    """Compute linear-interpolated percentile (0 <= pct <= 100)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (pct / 100.0) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(ordered[lo])
    frac = pos - lo
    return float(ordered[lo] * (1.0 - frac) + ordered[hi] * frac)


def bootstrap_ci(
    values: Sequence[float],
    n_resamples: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> Dict[str, float]:
    """Non-parametric percentile bootstrap 95% confidence interval for the mean."""
    n = len(values)
    if n == 0:
        return {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    mean_val = sum(values) / n
    if n == 1:
        return {"mean": round(mean_val, 6), "ci_low": round(mean_val, 6), "ci_high": round(mean_val, 6)}

    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_resamples):
        sample_sum = sum(values[rng.randrange(n)] for _ in range(n))
        means.append(sample_sum / n)
    means.sort()
    lo_idx = max(0, int(math.floor((alpha / 2.0) * (n_resamples - 1))))
    hi_idx = min(n_resamples - 1, int(math.ceil((1.0 - alpha / 2.0) * (n_resamples - 1))))
    return {
        "mean": round(mean_val, 6),
        "ci_low": round(means[lo_idx], 6),
        "ci_high": round(means[hi_idx], 6),
    }


def paired_bootstrap_delta_ci(
    baseline: Sequence[float],
    candidate: Sequence[float],
    n_resamples: int = 2000,
    seed: int = 42,
    alpha: float = 0.05,
) -> Dict[str, Any]:
    """Paired bootstrap 95% CI and two-sided empirical p-value for (candidate - baseline)."""
    if len(baseline) != len(candidate):
        raise ValueError("baseline and candidate sequences must have equal length")
    n = len(baseline)
    if n == 0:
        return {"delta_mean": 0.0, "ci_low": 0.0, "ci_high": 0.0, "statistically_significant": False}

    deltas = [cand - base for base, cand in zip(baseline, candidate)]
    obs_mean = sum(deltas) / n
    rng = random.Random(seed)
    boot_means: List[float] = []
    for _ in range(n_resamples):
        boot_means.append(sum(deltas[rng.randrange(n)] for _ in range(n)) / n)
    boot_means.sort()
    lo_idx = max(0, int(math.floor((alpha / 2.0) * (n_resamples - 1))))
    hi_idx = min(n_resamples - 1, int(math.ceil((1.0 - alpha / 2.0) * (n_resamples - 1))))
    ci_low = boot_means[lo_idx]
    ci_high = boot_means[hi_idx]
    # Zero outside CI indicates significant difference at alpha level
    significant = (ci_low > 0.0) or (ci_high < 0.0)
    return {
        "delta_mean": round(obs_mean, 6),
        "ci_low": round(ci_low, 6),
        "ci_high": round(ci_high, 6),
        "statistically_significant": significant,
    }


def evaluate_query_ranking(
    ranked_ids: Sequence[str],
    qrels: Dict[str, int],
    latency_ms: float,
) -> Dict[str, Any]:
    """Compute per-query retrieval metrics for k in {1,3,5,10}, MRR, and nDCG@10."""
    deduped: List[str] = []
    seen = set()
    for cid in ranked_ids:
        if cid not in seen:
            seen.add(cid)
            deduped.append(cid)

    return {
        "recall_at_1": recall_at_k(deduped, qrels, 1),
        "recall_at_3": recall_at_k(deduped, qrels, 3),
        "recall_at_5": recall_at_k(deduped, qrels, 5),
        "recall_at_10": recall_at_k(deduped, qrels, 10),
        "mrr": reciprocal_rank(deduped, qrels, k=10),
        "ndcg_at_10": ndcg_at_k(deduped, qrels, k=10),
        "latency_ms": float(latency_ms),
    }


def aggregate_query_metrics(
    per_query: Sequence[Dict[str, Any]],
    n_resamples: int = 2000,
    seed: int = 42,
) -> Dict[str, Any]:
    """Aggregate per-query metrics with bootstrap 95% CIs and latency percentiles."""
    metric_keys = ("recall_at_1", "recall_at_3", "recall_at_5", "recall_at_10", "mrr", "ndcg_at_10")
    summary: Dict[str, Any] = {"count": len(per_query)}
    for idx, key in enumerate(metric_keys):
        vals = [row[key] for row in per_query]
        summary[key] = bootstrap_ci(vals, n_resamples=n_resamples, seed=seed + idx)

    latencies = [row["latency_ms"] for row in per_query]
    summary["latency_ms"] = {
        "p50": round(percentile(latencies, 50), 2),
        "p95": round(percentile(latencies, 95), 2),
        "mean": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
    }
    return summary
