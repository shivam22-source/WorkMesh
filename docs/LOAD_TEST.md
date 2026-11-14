# WorkMesh Concurrency, Load Testing & Multi-Tenant ACL Verification

This document details the concurrency control, load test benchmarks, and multi-tenant ACL performance of WorkMesh under simulated production workloads.

---

## 1. Concurrency Limits & Backpressure Control

WorkMesh protects internal database connections and CPU embedding workers from starvation under burst traffic using an adaptive concurrency limiter on `/api/v1/search` and `/api/v1/ask`.

- **Concurrency Limit**: 15 concurrent active queries (`SEARCH_CONCURRENCY_LIMIT=15`).
- **Shedding Strategy**: Immediate `503 Service Unavailable` with `Retry-After: 1` header when active query slots are exhausted.
- **Fail-Fast Latency**: Excess requests fail fast (~20–300 ms) instead of queuing indefinitely and causing cascading timeouts.

---

## 2. Locust Load Test Benchmark

*Configuration: `SEARCH_CONCURRENCY_LIMIT=15`, `ef_search=100`, 52 distinct queries, 60s runs per concurrency tier on 13th Gen Intel Core i5-13500HX.*

Load tests were executed using Locust (`rag-python/loadtest/locustfile.py`) across 1 (baseline), 5, 10, 15, 25, 50, and 100 concurrent users against the local service. A pool of 52 distinct queries was used to prevent micro-cache skew.

The primary benchmark evaluated an employee identity (`employee_42`, member of `group_engineering` and `group_backend`) with access to **6,000 out of 10,000 chunks (60.0% of the corpus)**. An additional run evaluated 25 concurrent users under a low-access identity (`test_user_1`, access to **100 out of 10,000 chunks / 1.0% of the corpus**).

All reported latencies measure successful (2xx) responses exclusively:

| Concurrency Level & Identity | Total Requests | Successful (2xx) | 503 Backpressure Shed | Other Errors | P50 Latency (Success) | P95 Latency (Success) | Throughput (Success) |
|---|---|---|---|---|---|---|---|
| **1 User** (baseline, `employee_42`, 60% access) | 218 | 218 | 0 | 0 | **110.0 ms** | **230.0 ms** | 3.75 req/s |
| **5 Users** (`employee_42`, 60% access) | 1,012 | 1,012 | 0 | 0 | **120.0 ms** | **320.0 ms** | 17.36 req/s |
| **10 Users** (`employee_42`, 60% access) | 1,777 | 1,777 | 0 | 0 | **160.0 ms** | **520.0 ms** | 29.89 req/s |
| **15 Users** (`employee_42`, 60% access) | 2,285 | 2,282 | 3 | 0 | **210.0 ms** | **640.0 ms** | 38.37 req/s |
| **25 Users** (`employee_42`, 60% access) | 3,351 | 2,147 | 1,204 | 0 | **380.0 ms** | **1,100.0 ms** | 36.16 req/s |
| **50 Users** (`employee_42`, 60% access) | 4,424 | 1,802 | 2,622 | 0 | **760.0 ms** | **1,400.0 ms** | 30.35 req/s |
| **100 Users** (`employee_42`, 60% access) | 4,595 | 1,729 | 2,866 | 0 | **1,400.0 ms** | **2,400.0 ms** | 29.04 req/s |
| **25 Users (Low Access)** (`test_user_1`, 1% access) | 1,990 | 582 | 1,408 | 0 | **780.0 ms** | **1,500.0 ms** | 9.97 req/s |

### Hardware & Test Setup
- **Processor**: 13th Gen Intel(R) Core(TM) i5-13500HX (14 cores, 20 logical threads).
- **RAM**: 16 GB, Windows 11.
- **Topology**: FastAPI application (`127.0.0.1:8000`) and PostgreSQL 16 + pgvector container hosted on the same physical machine.
- **Embedding Provider**: Local HuggingFace `sentence-transformers` (`all-MiniLM-L6-v2`, 384 dimensions) running on CPU.

### Capacity Observations
1. **Unconstrained Throughput**: Up to 15 concurrent users, the service operates without shedding traffic, sustaining up to **38.37 successful requests/second** with p95 latency under 640 ms.
2. **Backpressure Containment**: Above 15 concurrent users, the limiter sheds excess requests with immediate HTTP 503 responses, preventing database connection exhaustion and preserving 29–36 successful req/s throughput.
3. **Low-Access Behavior**: For restricted identities (1% corpus access), candidate filtering requires deeper index scans, sustaining 9.97 successful req/s at 25 concurrent users with zero permission leaks.

---

## 3. Multi-Tenant ACL Recall Verification

*Configuration: `ef_search=100`, iterative scan (`hnsw.iterative_scan = 'relaxed_order'`), 30 queries across 4 permission tiers.*

When pushdown ACL filtering is applied after approximate nearest neighbor (ANN) vector retrieval, low-access users risk candidate starvation: index neighbors may be pruned by ACLs, returning fewer than the requested `limit` results.

WorkMesh addresses this using pgvector's `hnsw.iterative_scan = 'relaxed_order'` combined with an adaptive exact fallback when surviving rows $< \text{limit}$. Evaluated across 30 queries across 4 permission tiers:

| Tenant Access Tier | Accessible Corpus Share | Readable Chunks | Avg Results (Before) | Recall@5 (Before) | Avg Results (After) | Recall@5 (After) | Avg Latency (After) |
|---|---|---|:---:|:---:|:---:|:---:|:---:|
| **100% Access** (`test_user_100`) | 100.0% of corpus | 10,000 / 10,000 | 5.00 / 5 | 88.0% | 5.00 / 5 | 88.0% | 4.98 ms |
| **50% Access** (`test_user_50`) | 50.0% of corpus | 5,000 / 10,000 | 5.00 / 5 | 80.0% | 5.00 / 5 | 80.0% | 4.76 ms |
| **10% Access** (`test_user_10`) | 10.0% of corpus | 1,000 / 10,000 | 5.00 / 5 | 80.0% | 5.00 / 5 | 80.0% | 4.55 ms |
| **1% Access** (`test_user_1`) | 1.0% of corpus | 100 / 10,000 | **4.63 / 5** | 80.7% | **5.00 / 5** | **90.7%** | 12.97 ms |

- **Starvation Elimination**: For 1% access users, average returned results restored from 4.63 to 5.00/5, lifting Recall@5 from 80.7% to 90.7%.
- **Zero Leakage**: Zero unauthorized chunks returned across all 120 queries.
