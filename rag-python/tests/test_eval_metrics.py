"""Unit tests for graded IR metrics, nDCG@10, and bootstrap confidence intervals."""

import math

import pytest

from app.evaluation.metrics import (
    aggregate_query_metrics,
    bootstrap_ci,
    ndcg_at_k,
    paired_bootstrap_delta_ci,
    percentile,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_at_k_and_reciprocal_rank_graded():
    qrels = {"c1": 2, "c2": 1}
    ranked = ["other", "c2", "other2", "c1"]

    assert recall_at_k(ranked, qrels, 1) == 0.0
    assert recall_at_k(ranked, qrels, 3) == pytest.approx(0.5)
    assert recall_at_k(ranked, qrels, 5) == pytest.approx(1.0)
    assert reciprocal_rank(ranked, qrels) == pytest.approx(0.5)


def test_ndcg_at_k_graded_relevance():
    qrels = {"gold2": 2, "gold1": 1}
    # Ideal order: [gold2, gold1] -> 3/log2(2) + 1/log2(3)
    idcg = 3.0 + (1.0 / math.log2(3))
    assert ndcg_at_k(["gold2", "gold1"], qrels, k=10) == pytest.approx(1.0)

    # Swapped order: [gold1, gold2] -> 1/log2(2) + 3/log2(3)
    dcg_swapped = 1.0 + (3.0 / math.log2(3))
    assert ndcg_at_k(["gold1", "gold2"], qrels, k=10) == pytest.approx(dcg_swapped / idcg)


def test_bootstrap_ci_and_paired_delta():
    values = [1.0, 1.0, 0.0, 1.0, 0.5]
    res = bootstrap_ci(values, n_resamples=500, seed=42)
    assert res["ci_low"] <= res["mean"] <= res["ci_high"]
    assert res["mean"] == pytest.approx(0.7, abs=1e-6)

    same = paired_bootstrap_delta_ci(values, values, n_resamples=500, seed=42)
    assert same["delta_mean"] == 0.0
    assert same["statistically_significant"] is False

    improved = [v + 0.5 for v in values]
    sig = paired_bootstrap_delta_ci(values, improved, n_resamples=500, seed=42)
    assert sig["delta_mean"] == pytest.approx(0.5)
    assert sig["statistically_significant"] is True


def test_aggregate_query_metrics_and_percentiles():
    per_query = [
        {"recall_at_1": 1.0, "recall_at_3": 1.0, "recall_at_5": 1.0, "recall_at_10": 1.0, "mrr": 1.0, "ndcg_at_10": 1.0, "latency_ms": 10.0},
        {"recall_at_1": 0.0, "recall_at_3": 0.5, "recall_at_5": 0.5, "recall_at_10": 1.0, "mrr": 0.5, "ndcg_at_10": 0.6, "latency_ms": 30.0},
    ]
    agg = aggregate_query_metrics(per_query, n_resamples=200, seed=7)
    assert agg["count"] == 2
    assert agg["recall_at_1"]["mean"] == pytest.approx(0.5)
    assert agg["ndcg_at_10"]["mean"] == pytest.approx(0.8)
    assert agg["latency_ms"]["p50"] == pytest.approx(percentile([10.0, 30.0], 50))
