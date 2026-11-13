# PostgreSQL Query Performance & Execution Plans

All execution plans below were captured directly against the 10,000-chunk synthetic corpus in PostgreSQL 16 + `pgvector` using [`scripts/explain.py`](../scripts/explain.py):

```bash
cd rag-python
.venv/bin/python ../scripts/explain.py
```

- **Corpus size**: `10,000` chunks (`2,500` documents, `12,500+` ACL rows)
- **Indexes on `chunks`**: `chunks_pkey` (btree), `idx_chunks_document_id` (btree), `idx_chunks_tsv` (GIN), `idx_chunks_embedding_hnsw` (`hnsw (embedding vector_cosine_ops)`)
- **Indexes on `acl_references`**: `idx_acl_resource` (`resource_type, resource_id`), `idx_acl_principal` (`principal_type, principal_id`)
- **Session parameters**: `SET LOCAL hnsw.ef_search = 100; SET LOCAL hnsw.iterative_scan = 'relaxed_order';`

---

## Summary of Captured Plans (`EXPLAIN (ANALYZE, BUFFERS)`)

| Query Stage | Primary Index Used | Planning Time | Execution Time | Buffers | Key Observation |
|---|---|---:|---:|---|---|
| **Hybrid Lexical Stage** (`employee_42`, `limit=10`) | `idx_chunks_tsv` (GIN) + `idx_acl_principal` | 4.230 ms | 844.016 ms | `shared hit=1052 read=6` | GIN bitmap scan completes in `2.644 ms`; `Nested Loop Semi Join` filters `7,495,000` materialized ACL pairs over `2,000` text matches. |
| **Vector HNSW Candidate CTE** (`employee_42`, `candidate_k=100`, `limit=10`) | `idx_chunks_embedding_hnsw` (HNSW) + `documents_pkey` + `idx_acl_principal` | 0.417 ms | 100.107 ms | `shared hit=658 read=425` | Candidate CTE forces HNSW index scan (`Index Scan using idx_chunks_embedding_hnsw`), stopping at 10 surviving rows after post-filtering ACLs. |
| **Low-Access Exact Fallback** (`employee_01`, `limit=10`) | `Seq Scan on chunks` + `idx_acl_principal` | 0.353 ms | 223.456 ms | `shared hit=62695` | Correlated `OR` ACL join prevents planner from selecting HNSW directly; scans `10,000` chunks sequentially as adaptive fallback when candidate CTE starves. |

---

## 1. Hybrid Retrieval — Lexical Stage (`tsvector` GIN + Pushdown ACL)

`HybridRetriever` runs `PostgresKnowledgeRepository.search_lexical` alongside dense vector retrieval and fuses both ranked lists in Python via Reciprocal Rank Fusion (`k=60`).

```text
Limit  (cost=1288.60..1288.61 rows=1 width=495) (actual time=843.454..843.459 rows=10 loops=1)
  Buffers: shared hit=1052 read=6
  ->  Sort  (cost=1288.60..1288.61 rows=1 width=495) (actual time=843.453..843.457 rows=10 loops=1)
        Sort Key: (ts_rank_cd(c.tsv, '''payment'' & ''card'' & ''verif'''::tsquery)) DESC, c.created_at DESC
        Sort Method: top-N heapsort  Memory: 40kB
        Buffers: shared hit=1052 read=6
        ->  Nested Loop Semi Join  (cost=314.52..1288.59 rows=1 width=495) (actual time=5.169..842.237 rows=2000 loops=1)
              Join Filter: ((((a.resource_type)::text = 'SOURCE_RECORD'::text) AND ((a.resource_id)::text = (d.source_record_id)::text)) OR (((a.resource_type)::text = 'DOCUMENT'::text) AND ((a.resource_id)::text = (d.id)::text)) OR (((a.resource_type)::text = 'CHUNK'::text) AND ((a.resource_id)::text = (c.id)::text)))
              Rows Removed by Join Filter: 7495000
              Buffers: shared hit=1046 read=6
              ->  Hash Join  (cost=226.28..736.99 rows=160 width=1110) (actual time=4.491..10.440 rows=2000 loops=1)
                    Hash Cond: ((c.document_id)::text = (d.id)::text)
                    Buffers: shared hit=880 read=6
                    ->  Bitmap Heap Scan on chunks c  (cost=31.03..541.32 rows=160 width=936) (actual time=2.773..7.193 rows=2000 loops=1)
                          Recheck Cond: (tsv @@ '''payment'' & ''card'' & ''verif'''::tsquery)
                          Heap Blocks: exact=735
                          Buffers: shared hit=741 read=6
                          ->  Bitmap Index Scan on idx_chunks_tsv  (cost=0.00..30.99 rows=160 width=0) (actual time=2.644..2.644 rows=2000 loops=1)
                                Index Cond: (tsv @@ '''payment'' & ''card'' & ''verif'''::tsquery)
                                Buffers: shared hit=6 read=6
                    ->  Hash  (cost=164.00..164.00 rows=2500 width=174) (actual time=1.703..1.704 rows=2500 loops=1)
                          Buckets: 4096  Batches: 1  Memory Usage: 538kB
                          Buffers: shared hit=139
                          ->  Seq Scan on documents d  (cost=0.00..164.00 rows=2500 width=174) (actual time=0.010..0.725 rows=2500 loops=1)
                                Buffers: shared hit=139
              ->  Materialize  (cost=88.24..468.05 rows=19 width=24) (actual time=0.000..0.105 rows=3748 loops=2000)
                    Buffers: shared hit=166
                    ->  Bitmap Heap Scan on acl_references a  (cost=88.24..467.95 rows=19 width=24) (actual time=0.252..3.578 rows=7496 loops=1)
                          Recheck Cond: (((principal_type)::text = 'PUBLIC'::text) OR (((principal_type)::text = 'USER'::text) AND ((principal_id)::text = 'employee_42'::text)) OR (((principal_type)::text = 'GROUP'::text) AND ((principal_id)::text = ANY ('{group_engineering,group_backend}'::text[]))))
                          Filter: ((upper((permission)::text) = 'READ'::text) AND (((resource_type)::text = 'SOURCE_RECORD'::text) OR ((resource_type)::text = 'DOCUMENT'::text) OR ((resource_type)::text = 'CHUNK'::text)))
                          Heap Blocks: exact=153
                          Buffers: shared hit=166
                          ->  BitmapOr  (cost=88.24..88.24 rows=5106 width=0) (actual time=0.212..0.213 rows=0 loops=1)
                                Buffers: shared hit=13
                                ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..4.29 rows=1 width=0) (actual time=0.033..0.033 rows=0 loops=1)
                                      Index Cond: ((principal_type)::text = 'PUBLIC'::text)
                                      Buffers: shared hit=2
                                ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..4.30 rows=1 width=0) (actual time=0.006..0.007 rows=0 loops=1)
                                      Index Cond: (((principal_type)::text = 'USER'::text) AND ((principal_id)::text = 'employee_42'::text))
                                      Buffers: shared hit=2
                                ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..79.64 rows=5106 width=0) (actual time=0.172..0.172 rows=7500 loops=1)
                                      Index Cond: (((principal_type)::text = 'GROUP'::text) AND ((principal_id)::text = ANY ('{group_engineering,group_backend}'::text[])))
                                      Buffers: shared hit=9
Planning:
  Buffers: shared hit=520
Planning Time: 4.230 ms
Execution Time: 844.016 ms
```

---

## 2. Vector Retrieval — Two-Stage HNSW Candidate CTE + Post-Filter ACL

`PostgresKnowledgeRepository.search_vector` isolates nearest-neighbor ordering inside a `candidates` CTE (`LIMIT 100`) so PostgreSQL uses `idx_chunks_embedding_hnsw`, then applies document joins and ACL checks to the candidate rows.

```text
Limit  (cost=1188.22..2310.38 rows=1 width=523) (actual time=91.405..100.025 rows=10 loops=1)
  Buffers: shared hit=658 read=425
  ->  Nested Loop Semi Join  (cost=1188.22..2310.38 rows=1 width=523) (actual time=91.404..100.021 rows=10 loops=1)
        Join Filter: ((((a.resource_type)::text = 'SOURCE_RECORD'::text) AND ((a.resource_id)::text = (d.source_record_id)::text)) OR (((a.resource_type)::text = 'DOCUMENT'::text) AND ((a.resource_id)::text = (d.id)::text)) OR (((a.resource_type)::text = 'CHUNK'::text) AND ((a.resource_id)::text = (c.id)::text)))
        Rows Removed by Join Filter: 34030
        Buffers: shared hit=658 read=425
        ->  Nested Loop  (cost=1099.98..1790.12 rows=100 width=583) (actual time=89.085..93.233 rows=10 loops=1)
              Buffers: shared hit=525 read=425
              ->  Limit  (cost=1099.69..1681.12 rows=100 width=417) (actual time=89.045..92.824 rows=10 loops=1)
                    Buffers: shared hit=495 read=425
                    ->  Index Scan using idx_chunks_embedding_hnsw on chunks c  (cost=1099.69..20478.67 rows=3333 width=417) (actual time=89.044..92.820 rows=10 loops=1)
                          Order By: (embedding <=> '[-0.05124817,0.057880137,-0.018034626,-0.022030095,0.0076776766,-0.023786318,0.09037638,-0.02963439,0.024116287,-0.0818458,0.011334533,-0.027991375,0.041890442,0.0030290924,-0.09149569,-0.11812113,0.007887365,0.02060296,0.05209363,0.05200884,-0.08695039,-0.0052779033,-0.033780463,0.031563822,0.009492587,0.008806469,0.020792259,0.053315822,0.006848543,-0.025211852,0.09585649,0.086710185,0.078902915,-0.037808936,0.013215249,-0.053944435,-0.0026238167,-0.01803198,-0.025441015,-0.025085669,-0.048800316,-0.09037051,-0.03260437,-0.0018656045,0.026029602,0.07142933,0.02988025,0.07742514,-0.05283523,0.044825137,0.037036255,-0.027002217,-0.022553667,-0.016460972,-0.12563752,-0.004494475,0.077321224,-0.0743224,0.005194946,-0.03098448,0.05844486,0.0024190885,-0.034786366,0.067422576,-0.012786088,0.08750322,-0.0145271495,-0.026332824,-0.018969078,-0.0660158,0.04646665,-0.025531614,0.02896025,0.010585811,0.011586311,0.02226786,0.009823482,-0.03776233,0.016310431,0.003362431,-0.06759261,-0.012819472,0.035706505,-0.01743671,0.06946895,0.032922745,-0.0479609,0.06639118,-0.036319107,-0.14678694,0.09155618,0.072266944,0.018040538,-0.07307827,0.007948271,-0.009070197,0.014214412,-0.0839475,-0.010686516,0.051103964,0.00096758414,0.05131797,-0.029217608,-0.033187564,0.13981171,0.06725782,0.04604077,0.030064156,0.07905889,-0.033260982,-0.022861676,-0.057448015,0.046074215,0.015706733,-0.00791831,0.09283789,-0.025931625,0.082560875,0.010288757,0.06655163,0.010081372,-0.01866368,-0.060521953,-0.036651567,-0.035425354,-0.059778176,0.041370783,-2.4273606e-33,0.020929908,0.03839818,-0.0110813,-0.019241411,-0.01173348,-0.010697825,0.033237487,-0.018392729,-0.029356083,0.026272984,-0.017753705,-0.032500613,0.014911824,0.06010023,-0.011657388,0.079999976,-0.052437358,0.023435099,0.042761344,0.11903358,-0.015866889,-0.10311072,0.096700184,-0.010374025,0.047283333,0.023513477,-0.038897913,0.022377256,0.07856085,-0.029316194,0.02383223,-0.042242322,0.014443467,0.053765465,0.020773994,0.046842054,0.074766345,0.0057546627,0.0147355795,-0.043875515,0.0076616956,0.0014790159,-0.007254233,-0.049003802,0.005905707,0.00035145783,0.050991036,0.009476029,0.011432266,0.12462127,-0.029370312,0.041582987,-0.0929778,-0.054399118,-0.05897165,-0.06808511,0.007614314,0.04015352,-0.0066287504,-0.1247705,-0.035829347,-0.122165516,-0.05337283,-0.04085122,-0.028339311,-0.02727361,-0.06313733,-0.03133742,-0.0014595387,0.06844365,-0.06824965,0.03545287,0.07409433,0.003092375,-0.0047220504,0.026569016,-0.030125758,0.052379973,-0.07370529,0.040592987,-0.06725989,0.03453331,-0.01376874,0.039862655,0.021324337,0.0454078,0.07560487,-0.021835774,-0.0023948671,0.014984674,-0.020447573,0.029814698,0.06695262,0.028733864,0.09152401,1.6072272e-33,-0.0724064,-0.028900806,0.009187592,0.072050296,-0.085399866,-0.06555117,0.01213693,0.07088203,0.013692694,-0.010973693,0.0936339,0.03761365,0.006024098,-0.043545913,0.06262568,-0.069657646,-0.011046099,0.028653508,0.06660794,0.038640898,0.040962122,0.012424486,0.011540292,-0.00012460326,0.037221797,0.061269585,0.041639514,-0.11740371,-0.03901473,0.037277978,0.06758393,-0.018488996,-0.014499316,0.103723206,-0.009316424,-0.036320273,0.0077625075,0.1225804,0.09118028,0.016094096,-0.045015138,0.0025893524,-0.03259673,0.02267075,-0.04965114,-0.12175788,0.07648045,-0.0050276746,0.013681338,-0.037169445,-0.07510014,-0.028672718,0.011270613,0.044508576,-0.04114895,0.112065926,0.055675175,0.026370343,-0.011617748,-0.04154864,-0.037173368,0.03209002,0.060397256,-0.03318083,0.030006329,-0.007281728,0.013244993,0.046654243,0.079501055,0.06423974,-0.027597548,0.02087907,0.0029423588,0.07159288,0.047308903,-0.048087887,0.048471034,-0.01554586,-0.045222025,-0.044358414,-0.028444063,-0.044311747,-0.00073921744,0.057123125,-0.031339936,-0.04786856,-0.0037228186,-0.095381126,-0.028058236,-0.052638907,-0.022074528,0.06953943,0.010534269,-0.07484483,-0.06267261,-1.1532179e-08,-0.050020203,-0.014429003,-0.018366361,0.011846581,0.01604234,-0.021051023,-0.029744025,-0.100983545,-0.07549291,-0.062352303,0.03496816,-0.033416014,-0.049506545,-0.10963243,0.0044033015,-0.06527075,0.011404469,-0.096601196,-0.050445236,0.04474549,0.005962668,0.019695014,0.024094388,0.029688815,-0.0668805,0.0067871097,0.080657035,0.07515719,0.0077313846,-0.029092753,-0.005776049,0.038081296,0.07997849,-0.04395072,0.09935883,-0.016983246,0.052224476,0.05098473,-0.015427884,-0.009629292,0.0077789226,-0.036759734,-0.06943746,-0.10539667,0.0069241654,-0.010142857,-0.016691918,-0.054075252,0.012729219,-0.022464558,0.011333058,-0.021937327,0.038003534,0.0767593,-0.09973602,-0.07926719,0.038490538,0.00022413618,0.055580124,0.017193371,0.07333135,0.047935948,0.06025692,-0.10743171]'::vector)
                          Filter: ((embedding IS NOT NULL) AND ((- (embedding <#> embedding)) > '0'::double precision))
                          Buffers: shared hit=495 read=425
              ->  Memoize  (cost=0.29..4.11 rows=1 width=174) (actual time=0.039..0.039 rows=1 loops=10)
                    Cache Key: c.document_id
                    Cache Mode: logical
                    Hits: 0  Misses: 10  Evictions: 0  Overflows: 0  Memory Usage: 3kB
                    Buffers: shared hit=30
                    ->  Index Scan using documents_pkey on documents d  (cost=0.28..4.10 rows=1 width=174) (actual time=0.035..0.035 rows=1 loops=10)
                          Index Cond: ((id)::text = (c.document_id)::text)
                          Buffers: shared hit=30
        ->  Materialize  (cost=88.24..468.05 rows=19 width=24) (actual time=0.028..0.317 rows=3404 loops=10)
              Buffers: shared hit=133
              ->  Bitmap Heap Scan on acl_references a  (cost=88.24..467.95 rows=19 width=24) (actual time=0.276..1.635 rows=5876 loops=1)
                    Recheck Cond: (((principal_type)::text = 'PUBLIC'::text) OR (((principal_type)::text = 'USER'::text) AND ((principal_id)::text = 'employee_42'::text)) OR (((principal_type)::text = 'GROUP'::text) AND ((principal_id)::text = ANY ('{group_engineering,group_backend}'::text[]))))
                    Filter: ((upper((permission)::text) = 'READ'::text) AND (((resource_type)::text = 'SOURCE_RECORD'::text) OR ((resource_type)::text = 'DOCUMENT'::text) OR ((resource_type)::text = 'CHUNK'::text)))
                    Heap Blocks: exact=120
                    Buffers: shared hit=133
                    ->  BitmapOr  (cost=88.24..88.24 rows=5106 width=0) (actual time=0.251..0.252 rows=0 loops=1)
                          Buffers: shared hit=13
                          ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..4.29 rows=1 width=0) (actual time=0.004..0.004 rows=0 loops=1)
                                Index Cond: ((principal_type)::text = 'PUBLIC'::text)
                                Buffers: shared hit=2
                          ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..4.30 rows=1 width=0) (actual time=0.004..0.004 rows=0 loops=1)
                                Index Cond: (((principal_type)::text = 'USER'::text) AND ((principal_id)::text = 'employee_42'::text))
                                Buffers: shared hit=2
                          ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..79.64 rows=5106 width=0) (actual time=0.242..0.243 rows=7500 loops=1)
                                Index Cond: (((principal_type)::text = 'GROUP'::text) AND ((principal_id)::text = ANY ('{group_engineering,group_backend}'::text[])))
                                Buffers: shared hit=9
Planning:
  Buffers: shared hit=24
Planning Time: 0.417 ms
Execution Time: 100.107 ms
```

---

## 3. Adaptive Low-Access Fallback (Single-Stage ACL + Cosine Distance)

When fewer than `limit` rows survive the `candidates` CTE (for instance, when a user can access only ~1% of chunks), `search_vector` runs the single-stage ACL-filtered cosine distance query within the same `SET LOCAL` transaction. Because the optimizer cannot push the multi-table `OR` ACL filter into the HNSW index scan, it performs a full `Seq Scan on chunks`.

```text
Limit  (cost=3035.32..3035.32 rows=1 width=523) (actual time=223.421..223.425 rows=0 loops=1)
  Buffers: shared hit=62695
  ->  Sort  (cost=3035.32..3035.32 rows=1 width=523) (actual time=223.421..223.424 rows=0 loops=1)
        Sort Key: ((c.embedding <=> '[-0.05124817,0.057880137,-0.018034626,-0.022030095,0.0076776766,-0.023786318,0.09037638,-0.02963439,0.024116287,-0.0818458,0.011334533,-0.027991375,0.041890442,0.0030290924,-0.09149569,-0.11812113,0.007887365,0.02060296,0.05209363,0.05200884,-0.08695039,-0.0052779033,-0.033780463,0.031563822,0.009492587,0.008806469,0.020792259,0.053315822,0.006848543,-0.025211852,0.09585649,0.086710185,0.078902915,-0.037808936,0.013215249,-0.053944435,-0.0026238167,-0.01803198,-0.025441015,-0.025085669,-0.048800316,-0.09037051,-0.03260437,-0.0018656045,0.026029602,0.07142933,0.02988025,0.07742514,-0.05283523,0.044825137,0.037036255,-0.027002217,-0.022553667,-0.016460972,-0.12563752,-0.004494475,0.077321224,-0.0743224,0.005194946,-0.03098448,0.05844486,0.0024190885,-0.034786366,0.067422576,-0.012786088,0.08750322,-0.0145271495,-0.026332824,-0.018969078,-0.0660158,0.04646665,-0.025531614,0.02896025,0.010585811,0.011586311,0.02226786,0.009823482,-0.03776233,0.016310431,0.003362431,-0.06759261,-0.012819472,0.035706505,-0.01743671,0.06946895,0.032922745,-0.0479609,0.06639118,-0.036319107,-0.14678694,0.09155618,0.072266944,0.018040538,-0.07307827,0.007948271,-0.009070197,0.014214412,-0.0839475,-0.010686516,0.051103964,0.00096758414,0.05131797,-0.029217608,-0.033187564,0.13981171,0.06725782,0.04604077,0.030064156,0.07905889,-0.033260982,-0.022861676,-0.057448015,0.046074215,0.015706733,-0.00791831,0.09283789,-0.025931625,0.082560875,0.010288757,0.06655163,0.010081372,-0.01866368,-0.060521953,-0.036651567,-0.035425354,-0.059778176,0.041370783,-2.4273606e-33,0.020929908,0.03839818,-0.0110813,-0.019241411,-0.01173348,-0.010697825,0.033237487,-0.018392729,-0.029356083,0.026272984,-0.017753705,-0.032500613,0.014911824,0.06010023,-0.011657388,0.079999976,-0.052437358,0.023435099,0.042761344,0.11903358,-0.015866889,-0.10311072,0.096700184,-0.010374025,0.047283333,0.023513477,-0.038897913,0.022377256,0.07856085,-0.029316194,0.02383223,-0.042242322,0.014443467,0.053765465,0.020773994,0.046842054,0.074766345,0.0057546627,0.0147355795,-0.043875515,0.0076616956,0.0014790159,-0.007254233,-0.049003802,0.005905707,0.00035145783,0.050991036,0.009476029,0.011432266,0.12462127,-0.029370312,0.041582987,-0.0929778,-0.054399118,-0.05897165,-0.06808511,0.007614314,0.04015352,-0.0066287504,-0.1247705,-0.035829347,-0.122165516,-0.05337283,-0.04085122,-0.028339311,-0.02727361,-0.06313733,-0.03133742,-0.0014595387,0.06844365,-0.06824965,0.03545287,0.07409433,0.003092375,-0.0047220504,0.026569016,-0.030125758,0.052379973,-0.07370529,0.040592987,-0.06725989,0.03453331,-0.01376874,0.039862655,0.021324337,0.0454078,0.07560487,-0.021835774,-0.0023948671,0.014984674,-0.020447573,0.029814698,0.06695262,0.028733864,0.09152401,1.6072272e-33,-0.0724064,-0.028900806,0.009187592,0.072050296,-0.085399866,-0.06555117,0.01213693,0.07088203,0.013692694,-0.010973693,0.0936339,0.03761365,0.006024098,-0.043545913,0.06262568,-0.069657646,-0.011046099,0.028653508,0.06660794,0.038640898,0.040962122,0.012424486,0.011540292,-0.00012460326,0.037221797,0.061269585,0.041639514,-0.11740371,-0.03901473,0.037277978,0.06758393,-0.018488996,-0.014499316,0.103723206,-0.009316424,-0.036320273,0.0077625075,0.1225804,0.09118028,0.016094096,-0.045015138,0.0025893524,-0.03259673,0.02267075,-0.04965114,-0.12175788,0.07648045,-0.0050276746,0.013681338,-0.037169445,-0.07510014,-0.028672718,0.011270613,0.044508576,-0.04114895,0.112065926,0.055675175,0.026370343,-0.011617748,-0.04154864,-0.037173368,0.03209002,0.060397256,-0.03318083,0.030006329,-0.007281728,0.013244993,0.046654243,0.079501055,0.06423974,-0.027597548,0.02087907,0.0029423588,0.07159288,0.047308903,-0.048087887,0.048471034,-0.01554586,-0.045222025,-0.044358414,-0.028444063,-0.044311747,-0.00073921744,0.057123125,-0.031339936,-0.04786856,-0.0037228186,-0.095381126,-0.028058236,-0.052638907,-0.022074528,0.06953943,0.010534269,-0.07484483,-0.06267261,-1.1532179e-08,-0.050020203,-0.014429003,-0.018366361,0.011846581,0.01604234,-0.021051023,-0.029744025,-0.100983545,-0.07549291,-0.062352303,0.03496816,-0.033416014,-0.049506545,-0.10963243,0.0044033015,-0.06527075,0.011404469,-0.096601196,-0.050445236,0.04474549,0.005962668,0.019695014,0.024094388,0.029688815,-0.0668805,0.0067871097,0.080657035,0.07515719,0.0077313846,-0.029092753,-0.005776049,0.038081296,0.07997849,-0.04395072,0.09935883,-0.016983246,0.052224476,0.05098473,-0.015427884,-0.009629292,0.0077789226,-0.036759734,-0.06943746,-0.10539667,0.0069241654,-0.010142857,-0.016691918,-0.054075252,0.012729219,-0.022464558,0.011333058,-0.021937327,0.038003534,0.0767593,-0.09973602,-0.07926719,0.038490538,0.00022413618,0.055580124,0.017193371,0.07333135,0.047935948,0.06025692,-0.10743171]'::vector))
        Sort Method: quicksort  Memory: 25kB
        Buffers: shared hit=62695
        ->  Nested Loop Semi Join  (cost=203.84..3035.31 rows=1 width=523) (actual time=223.418..223.420 rows=0 loops=1)
              Join Filter: ((((a.resource_type)::text = 'SOURCE_RECORD'::text) AND ((a.resource_id)::text = (d.source_record_id)::text)) OR (((a.resource_type)::text = 'DOCUMENT'::text) AND ((a.resource_id)::text = (d.id)::text)) OR (((a.resource_type)::text = 'CHUNK'::text) AND ((a.resource_id)::text = (c.id)::text)))
              Buffers: shared hit=62695
              ->  Hash Join  (cost=195.25..2931.01 rows=3333 width=593) (actual time=0.878..221.701 rows=10000 loops=1)
                    Hash Cond: ((c.document_id)::text = (d.id)::text)
                    Buffers: shared hit=62691
                    ->  Seq Scan on chunks c  (cost=0.00..2727.00 rows=3333 width=419) (actual time=0.135..216.771 rows=10000 loops=1)
                          Filter: ((embedding IS NOT NULL) AND ((- (embedding <#> embedding)) > '0'::double precision))
                          Buffers: shared hit=62552
                    ->  Hash  (cost=164.00..164.00 rows=2500 width=174) (actual time=0.737..0.738 rows=2500 loops=1)
                          Buckets: 4096  Batches: 1  Memory Usage: 538kB
                          Buffers: shared hit=139
                          ->  Seq Scan on documents d  (cost=0.00..164.00 rows=2500 width=174) (actual time=0.003..0.273 rows=2500 loops=1)
                                Buffers: shared hit=139
              ->  Materialize  (cost=8.59..12.63 rows=1 width=24) (actual time=0.000..0.000 rows=0 loops=10000)
                    Buffers: shared hit=4
                    ->  Bitmap Heap Scan on acl_references a  (cost=8.59..12.62 rows=1 width=24) (actual time=0.049..0.050 rows=0 loops=1)
                          Recheck Cond: (((principal_type)::text = 'PUBLIC'::text) OR (((principal_type)::text = 'USER'::text) AND ((principal_id)::text = 'employee_01'::text)))
                          Filter: ((upper((permission)::text) = 'READ'::text) AND (((resource_type)::text = 'SOURCE_RECORD'::text) OR ((resource_type)::text = 'DOCUMENT'::text) OR ((resource_type)::text = 'CHUNK'::text)))
                          Buffers: shared hit=4
                          ->  BitmapOr  (cost=8.59..8.59 rows=1 width=0) (actual time=0.048..0.049 rows=0 loops=1)
                                Buffers: shared hit=4
                                ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..4.29 rows=1 width=0) (actual time=0.003..0.004 rows=0 loops=1)
                                      Index Cond: ((principal_type)::text = 'PUBLIC'::text)
                                      Buffers: shared hit=2
                                ->  Bitmap Index Scan on idx_acl_principal  (cost=0.00..4.30 rows=1 width=0) (actual time=0.044..0.044 rows=0 loops=1)
                                      Index Cond: (((principal_type)::text = 'USER'::text) AND ((principal_id)::text = 'employee_01'::text))
                                      Buffers: shared hit=2
Planning:
  Buffers: shared hit=13
Planning Time: 0.353 ms
Execution Time: 223.456 ms
```
