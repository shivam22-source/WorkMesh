# Retrieval Quality & Latency Experiments (`queries_v2`)

Every experiment below was executed against the 10,077-chunk live PostgreSQL 16 + `pgvector` corpus using [`data/evaluation/queries_v2.jsonl`](../data/evaluation/queries_v2.jsonl) (`60` queries: `20` exact-identifier, `20` semantic paraphrases with `<= 1` shared content word, `20` multi-source queries) via `python -m app.cli.sweep_v2`.

Raw JSON: [`data/evaluation/results/sweep_v2_results.json`](../data/evaluation/results/sweep_v2_results.json).

---

## Step 3 Parameter Sweep: Diagnosing Semantic & Multi-Source Weakness

| Experiment | Group | `ef_search` | Pool | RRF `k` | `w_lex / w_vec` | Routing | Overall R@5 [95% CI] | Overall nDCG@10 | Overall MRR | ID R@5 | Sem R@5 | Multi R@5 | p50 / p95 ms |
|---|---|---:|---:|---:|---|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline_k60_pool20_ef100` | baseline | 100 | 20 | 60 | 1.0/1.0 | off | 45.4% [33.8, 57.9] | 0.4533 | 0.4875 | 96.2% | 20.0% | 20.0% | 130.3 / 170.9 |
| `pool_40_ef100` | candidate_pool | 100 | 40 | 60 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7263 | 0.7450 | 96.2% | 50.0% | 72.5% | 166.7 / 229.7 |
| `pool_80_ef100` | candidate_pool | 100 | 80 | 60 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 450.4 / 540.1 |
| `pool_120_ef100` | candidate_pool | 100 | 120 | 60 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 614.9 / 724.8 |
| `ef200_pool20` | hnsw_ef_search | 200 | 20 | 60 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7259 | 0.7450 | 96.2% | 50.0% | 72.5% | 141.6 / 193.8 |
| `ef300_pool20` | hnsw_ef_search | 300 | 20 | 60 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7259 | 0.7450 | 96.2% | 50.0% | 72.5% | 147.1 / 196.9 |
| `ef400_pool50` | hnsw_ef_search | 400 | 50 | 60 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 163.1 / 231.5 |
| `rrf_k10_ef300_p50` | rrf_k | 300 | 50 | 10 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 166.5 / 238.4 |
| `rrf_k20_ef300_p50` | rrf_k | 300 | 50 | 20 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 169.1 / 229.0 |
| `rrf_k40_ef300_p50` | rrf_k | 300 | 50 | 40 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 152.8 / 223.8 |
| `rrf_k60_ef300_p50` | rrf_k | 300 | 50 | 60 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 166.2 / 214.3 |
| `rrf_k100_ef300_p50` | rrf_k | 300 | 50 | 100 | 1.0/1.0 | off | 72.9% [60.4, 83.3] | 0.7268 | 0.7450 | 96.2% | 50.0% | 72.5% | 160.6 / 221.5 |
| `weights_lex1.5_vec0.5` | weights | 300 | 50 | 20 | 1.5/0.5 | off | 74.2% [61.7, 84.2] | 0.7306 | 0.7450 | 100.0% | 50.0% | 72.5% | 161.6 / 229.7 |
| `weights_lex0.5_vec1.5` | weights | 300 | 50 | 20 | 0.5/1.5 | off | 69.2% [56.7, 80.0] | 0.6806 | 0.6971 | 85.0% | 50.0% | 72.5% | 173.2 / 233.0 |
| `weights_lex0.3_vec1.7` | weights | 300 | 50 | 20 | 0.3/1.7 | off | 68.8% [56.7, 79.6] | 0.6769 | 0.6950 | 83.8% | 50.0% | 72.5% | 173.8 / 209.8 |
| `weights_lex0.0_vec1.0` | weights | 300 | 50 | 20 | 0.0/1.0 | off | 68.3% [55.8, 79.2] | 0.6689 | 0.6867 | 82.5% | 50.0% | 72.5% | 165.9 / 229.7 |
| `routing_balanced_id1.6_sem1.6` | routing | 300 | 50 | 20 | 1.0/1.0 | on (id=[1.6, 0.4], sem=[0.4, 1.6]) | 74.2% [61.7, 84.2] | 0.7306 | 0.7450 | 100.0% | 50.0% | 72.5% | 177.2 / 226.4 |
| `routing_strong_id1.8_sem1.8` | routing | 300 | 50 | 20 | 1.0/1.0 | on (id=[1.8, 0.2], sem=[0.2, 1.8]) | 74.2% [61.7, 84.2] | 0.7306 | 0.7450 | 100.0% | 50.0% | 72.5% | 175.0 / 244.5 |
| `routing_id1.6_sem1.6_k60` | routing | 300 | 50 | 60 | 1.0/1.0 | on (id=[1.6, 0.4], sem=[0.4, 1.6]) | 74.2% [61.7, 84.2] | 0.7306 | 0.7450 | 100.0% | 50.0% | 72.5% | 174.3 / 224.0 |
| `or_fallback_ef300_p50_noroute` | lexical_or_fallback | 300 | 50 | 60 | 1.0/1.0 | off | 70.8% [59.6, 81.2] | 0.6802 | 0.6673 | 92.5% | 45.0% | 75.0% | 1725.4 / 3862.1 |
| `or_fallback_routing_id1.6_sem1.6` | lexical_or_fallback | 300 | 50 | 20 | 1.0/1.0 | on (id=[1.6, 0.4], sem=[0.4, 1.6]) | 73.3% [61.7, 83.3] | 0.7365 | 0.7500 | 100.0% | 45.0% | 75.0% | 1730.9 / 3929.6 |

### Key Findings (Including What Did Not Help)

1. **Root cause of initial low semantic & multi-source recall (`45.4% -> 72.9%` R@5):**
   - At the original baseline (`hnsw.ef_search = 100`, `candidate_pool_size = 20`), pgvector HNSW traversal became trapped inside the five 2,000-chunk synthetic `scale:*` template clusters, returning cloned `scale` chunks (`0.28` similarity) instead of global rank #1/#2 `eval2` matches (`0.55` similarity).
   - Raising `SET LOCAL hnsw.ef_search = 200` with `candidate_pool_size = 20` lifted Overall Recall@5 by **+27.5 pp** (`45.4% -> 72.9%`), Semantic R@5 from `20.0% -> 50.0%`, and Multi-Source R@5 from `20.0% -> 72.5%` for **+11.3 ms p50 latency** (`130.3 -> 141.6 ms`, `p95 = 193.8 ms`).
   - Raising `ef_search` further to `300` or `400` produced **0.0 pp additional recall** over `200`.

2. **Expanding candidate pool (`pool = 80, 120`) did NOT help beyond `40`:**
   - At `pool = 80` and `pool = 120` (`ef_search = 100`), Overall Recall@5 stayed flat at `72.9%` (`nDCG@10 = 0.7268` vs `0.7259`), while `p50` latency degraded from `141.6 ms` to `450.4 ms` (`pool = 80`) and `614.9 ms` (`pool = 120`). Rejected.

3. **RRF smoothing `k` sweep (`k = 10, 20, 40, 60, 100`) made 0.0 pp difference:**
   - Because strict `plainto_tsquery` returns `0` lexical hits on natural-language semantic paraphrases (`0.0%`) and long multi-source questions (`0.0%`), vector ranks alone determine ordering on those 40 queries regardless of `k`. Keeping `k = 60` (standard Cormack default).

4. **Static per-retriever weights hurt exact identifiers:**
   - Static vector-heavy weights `(0.5/1.5)`, `(0.3/1.7)`, and vector-only `(0.0/1.0)` degraded Overall R@5 (`72.9% -> 69.2% -> 68.8% -> 68.3%`) because Exact-Identifier R@5 fell from `96.2%` down to `82.5%`. Rejected.

5. **Query-type routing (`routing_id1.6_sem1.6_k60`) improved Overall R@5 to `74.2%` (`+1.3 pp` over `ef200`):**
   - Routing identifier-looking queries (tickets, SHAs, snake_case/CamelCase symbols) toward lexical `(1.6, 0.4)` and natural-language semantic queries toward vector `(0.4, 1.6)` lifted Exact-Identifier R@5 from **`96.2% -> 100.0%`** without degrading Semantic (`50.0%`) or Multi-Source (`72.5%`) recall, bringing Overall nDCG@10 to **`0.7306`** and MRR to **`0.7450`**. Adopted alongside `hnsw_ef_search = 200`.

6. **Lexical `OR` fallback (`replace(plainto_tsquery, '&', '|')`) did NOT survive cost-benefit:**
   - Appending disjunctive `OR` matches edged Multi-Source R@5 up slightly (`72.5% -> 75.0%`), but noisy 1-token matches from the 10k background chunks dropped Semantic R@5 (`50.0% -> 45.0%`) and exploded latency **10x–20x** (`p50 = 1,730.9 ms`, `p95 = 3,929.6 ms`). Rejected (`lexical_or_fallback = False` kept disabled).
