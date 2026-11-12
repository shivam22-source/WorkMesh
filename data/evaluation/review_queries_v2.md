# Evaluation Set Manual Review (`queries_v2`)

Total queries: **60** | Priority sample size: **15** (`seed=42`)

## REVIEW THESE 15

### qv2-multi-01

- **Query ID:** `qv2-multi-01`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** Why did we switch session cookies to SameSite=Lax and which PR implemented it?

#### Gold Chunk `doc:github:company/auth-gateway:pr:701:c0` — grade `2` — source `github`

```text
Pull Request #701 resolves V2-101 by updating SessionCookieFactory.build() to emit SameSite=Lax with HttpOnly and Secure flags enabled across all gateways.
```

#### Gold Chunk `doc:slack:C04SEC:thread:1700000201.000100:c0` — grade `2` — source `slack`

```text
V2-101 postmortem in Slack: SameSite=Strict dropped session cookies during third-party IdP redirects; security agreed switching to SameSite=Lax preserves CSRF protection while fixing SSO logins.
```

### qv2-id-08

- **Query ID:** `qv2-id-08`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** SlidingWindowRateLimiter

#### Gold Chunk `doc:github:company/edge-gateway:pr:742:c0` — grade `2` — source `github`

```text
PR #742 adds SlidingWindowRateLimiter using atomic Lua scripts to enforce per-tenant burst quotas across API gateway replicas.
```

#### Gold Chunk `doc:github:company/edge-gateway:pr:742:c1` — grade `1` — source `github`

```text
Benchmark tests for SlidingWindowRateLimiter verify 0.4ms p99 overhead at 12,000 requests/sec.
```

### qv2-id-02

- **Query ID:** `qv2-id-02`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** DC-1006

#### Gold Chunk `scale:doc:00006:c0` — grade `2` — source `github`

```text
[GITHUB] Tune HikariCP connection pool settings for high concurrency (DC-1006)
Section 1: Resolves ticket DC-1006: payment service was exhausting connection pool during peak traffic. Increased maxPoolSize to 50, tuned connectionTimeout to 250ms, and enabled leakDetectionThreshold at 2000ms to eliminate thread starvation. Detailed technical notes on database. Trace reference: DC-1006.
```

#### Gold Chunk `scale:doc:00006:c1` — grade `1` — source `github`

```text
[GITHUB] Tune HikariCP connection pool settings for high concurrency (DC-1006)
Section 2: Resolves ticket DC-1006: payment service was exhausting connection pool during peak traffic. Increased maxPoolSize to 50, tuned connectionTimeout to 250ms, and enabled leakDetectionThreshold at 2000ms to eliminate thread starvation. Detailed technical notes on connection pool. Trace reference: DC-1006.
```

#### Gold Chunk `scale:doc:00006:c2` — grade `1` — source `github`

```text
[GITHUB] Tune HikariCP connection pool settings for high concurrency (DC-1006)
Section 3: Resolves ticket DC-1006: payment service was exhausting connection pool during peak traffic. Increased maxPoolSize to 50, tuned connectionTimeout to 250ms, and enabled leakDetectionThreshold at 2000ms to eliminate thread starvation. Detailed technical notes on HikariCP. Trace reference: DC-1006.
```

#### Gold Chunk `scale:doc:00006:c3` — grade `1` — source `github`

```text
[GITHUB] Tune HikariCP connection pool settings for high concurrency (DC-1006)
Section 4: Resolves ticket DC-1006: payment service was exhausting connection pool during peak traffic. Increased maxPoolSize to 50, tuned connectionTimeout to 250ms, and enabled leakDetectionThreshold at 2000ms to eliminate thread starvation. Detailed technical notes on timeout. Trace reference: DC-1006.
```

### qv2-multi-08

- **Query ID:** `qv2-multi-08`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** What schema migration blocker was raised in Slack for pgvector 384 dims and which PR updated the SQL?

#### Gold Chunk `doc:github:company/workmesh:pr:708:c0` — grade `2` — source `github`

```text
Pull Request #708 delivers V2-108 by migrating DDL schema chunks.embedding to vector(384) and removing legacy zero-padding code.
```

#### Gold Chunk `doc:slack:C08SRCH:thread:1700000208.000100:c0` — grade `2` — source `slack`

```text
V2-108 discussion: padding 384-dim MiniLM outputs to 1536 zeroes inflated HNSW index memory 4x; agreed migrating schema directly to vector(384).
```

### qv2-id-18

- **Query ID:** `qv2-id-18`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** OPS-772

#### Gold Chunk `doc:github:company/infra-runbooks:pr:89:c0` — grade `2` — source `github`

```text
OPS-772 fixed intermittent DNS lookup timeouts under EKS burst autoscaling by raising nf_conntrack_max to 262144.
```

### qv2-id-16

- **Query ID:** `qv2-id-16`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** workmesh_queue_saturation_ratio

#### Gold Chunk `doc:slack:C10OBS:thread:1700000016.000100:c0` — grade `2` — source `slack`

```text
Page on-call SRE if workmesh_queue_saturation_ratio stays above 0.85 for 3 consecutive evaluation windows in Prometheus.
```

### qv2-id-15

- **Query ID:** `qv2-id-15`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** idx_ledger_entries_created

#### Gold Chunk `doc:slack:C09DBA:thread:1700000015.000100:c0` — grade `2` — source `slack`

```text
Build idx_ledger_entries_created using CREATE INDEX CONCURRENTLY during low traffic and monitor pg_stat_progress_create_index.
```

### qv2-id-09

- **Query ID:** `qv2-id-09`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_01` (groups: `group_engineering`, `group_finance`, `group_security`)
- **Query Text:** FIN-418

#### Gold Chunk `doc:email:finance.ops@company.internal:msg-fin-418:c0` — grade `2` — source `email`

```text
Ticket FIN-418 tracks a $14,220 settlement timing delta between European SEPA batch clearing and nightly ledger ingestion.
```

### qv2-multi-17

- **Query ID:** `qv2-multi-17`
- **Query Type:** `multi_source`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** Why did SRE ask in email to add Prometheus histogram buckets under 50ms and which PR exported /metrics?

#### Gold Chunk `doc:email:sre@company.internal:msg-v2-117:c0` — grade `2` — source `email`

```text
V2-117 SRE request: coarse 100ms buckets hide sub-50ms degradation during warm cache hits; add 10ms and 25ms boundaries to latency histograms.
```

#### Gold Chunk `doc:github:company/workmesh:pr:717:c0` — grade `2` — source `github`

```text
Pull Request #717 resolves V2-117 by exposing workmesh_http_request_duration_seconds buckets including 0.01 and 0.025 on GET /metrics.
```

### qv2-id-07

- **Query ID:** `qv2-id-07`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** 9f3e21ab4c8d

#### Gold Chunk `doc:github:company/ledger-core:commit:9f3e21ab4c8d:c0` — grade `2` — source `github`

```text
Commit 9f3e21ab4c8d updates MultiCurrencyPostingEngine to accumulate sub-cent remainders before posting rounding adjustment entries.
```

### qv2-multi-04

- **Query ID:** `qv2-multi-04`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** Why did Slack engineers pick Zstandard over Gzip for trace compression and what PR rolled it out?

#### Gold Chunk `doc:github:company/otel-config:pr:704:c0` — grade `2` — source `github`

```text
Pull Request #704 completes V2-104 by configuring compression: zstd on all production OpenTelemetry Collector otlp exporter pipelines.
```

#### Gold Chunk `doc:slack:C10OBS:thread:1700000204.000100:c0` — grade `2` — source `slack`

```text
V2-104 benchmark consensus: Zstandard level 3 reduced trace egress bandwidth 42% over Gzip while cutting collector CPU overhead by 35%.
```

### qv2-multi-12

- **Query ID:** `qv2-multi-12`
- **Query Type:** `multi_source`
- **Identity:** `employee_10` (groups: `group_engineering`)
- **Query Text:** What email warned about NAT gateway port exhaustion and which PR switched to VPC endpoints?

#### Gold Chunk `doc:email:sre@company.internal:msg-v2-112:c0` — grade `2` — source `email`

```text
V2-112 incident email: High S3/ECR pull concurrency saturated the 55k ephemeral NAT Gateway ports, causing external TLS connect timeouts.
```

#### Gold Chunk `doc:github:company/aws-network:pr:712:c0` — grade `2` — source `github`

```text
Pull Request #712 solves V2-112 by adding Gateway VPC endpoint for S3 and Interface endpoints for ecr.dkr to bypass NAT Gateways.
```

### qv2-sem-15

- **Query ID:** `qv2-sem-15`
- **Query Type:** `semantic`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** blocking malicious injected browser scripts with cryptographic header per request

#### Gold Chunk `doc:github:company/web-console:pr:615:c0` — grade `2` — source `github`

```text
Generated random Base64 nonces per HTTP response paired with CSP script-src directives so unauthorized inline DOM XSS payloads fail execution.
```

### qv2-id-06

- **Query ID:** `qv2-id-06`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** ERR_MTLS_HANDSHAKE_495

#### Gold Chunk `doc:slack:C04SEC:thread:1700000001.000100:c0` — grade `2` — source `slack`

```text
Alert triggered in edge proxy: ERR_MTLS_HANDSHAKE_495 spikes whenever partner leaf certificates lack ExtendedKeyUsage clientAuth.
```

#### Gold Chunk `doc:slack:C04SEC:thread:1700000001.000100:c1` — grade `1` — source `slack`

```text
Mitigation step for ERR_MTLS_HANDSHAKE_495: upload intermediate bundle to truststore-prod-v4 and drain unhealthy Envoy pods.
```

### qv2-sem-18

- **Query ID:** `qv2-sem-18`
- **Query Type:** `semantic`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** offloading multi-hundred megabyte billing CSV archives away from API server workers

#### Gold Chunk `doc:github:company/export-api:pr:618:c0` — grade `2` — source `github`

```text
Replaced streaming FastAPI FileResponse endpoints with 15-minute KMS-authorized pre-signed S3 URLs so Python ASGI workers stay responsive.
```

## REMAINING QUERIES (45)

### qv2-id-01

- **Query ID:** `qv2-id-01`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** DC-1000

#### Gold Chunk `scale:doc:00000:c0` — grade `2` — source `github`

```text
[GITHUB] Fix null verification in payment card validation (DC-1000)
Section 1: Resolves ticket DC-1000: empty verification payloads were throwing NullPointerException during checkout. Updated PaymentValidationService to validate card tokens defensively and return HTTP 400 Bad Request instead of HTTP 500 crash. Detailed technical notes on payment. Trace reference: DC-1000.
```

#### Gold Chunk `scale:doc:00000:c1` — grade `1` — source `github`

```text
[GITHUB] Fix null verification in payment card validation (DC-1000)
Section 2: Resolves ticket DC-1000: empty verification payloads were throwing NullPointerException during checkout. Updated PaymentValidationService to validate card tokens defensively and return HTTP 400 Bad Request instead of HTTP 500 crash. Detailed technical notes on validation. Trace reference: DC-1000.
```

#### Gold Chunk `scale:doc:00000:c2` — grade `1` — source `github`

```text
[GITHUB] Fix null verification in payment card validation (DC-1000)
Section 3: Resolves ticket DC-1000: empty verification payloads were throwing NullPointerException during checkout. Updated PaymentValidationService to validate card tokens defensively and return HTTP 400 Bad Request instead of HTTP 500 crash. Detailed technical notes on card verification. Trace reference: DC-1000.
```

#### Gold Chunk `scale:doc:00000:c3` — grade `1` — source `github`

```text
[GITHUB] Fix null verification in payment card validation (DC-1000)
Section 4: Resolves ticket DC-1000: empty verification payloads were throwing NullPointerException during checkout. Updated PaymentValidationService to validate card tokens defensively and return HTTP 400 Bad Request instead of HTTP 500 crash. Detailed technical notes on NullPointerException. Trace reference: DC-1000.
```

### qv2-id-03

- **Query ID:** `qv2-id-03`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** DC-1008

#### Gold Chunk `scale:doc:00008:c0` — grade `2` — source `email`

```text
[EMAIL] Optimize Kafka consumer group commit interval and backpressure (DC-1008)
Section 1: Resolves ticket DC-1008: transaction event consumer was experiencing severe lag under burst load. Switched to manual asynchronous commit and configured a dead letter queue (DLQ) for malformed records. Detailed technical notes on Kafka. Trace reference: DC-1008.
```

#### Gold Chunk `scale:doc:00008:c1` — grade `1` — source `email`

```text
[EMAIL] Optimize Kafka consumer group commit interval and backpressure (DC-1008)
Section 2: Resolves ticket DC-1008: transaction event consumer was experiencing severe lag under burst load. Switched to manual asynchronous commit and configured a dead letter queue (DLQ) for malformed records. Detailed technical notes on consumer lag. Trace reference: DC-1008.
```

#### Gold Chunk `scale:doc:00008:c2` — grade `1` — source `email`

```text
[EMAIL] Optimize Kafka consumer group commit interval and backpressure (DC-1008)
Section 3: Resolves ticket DC-1008: transaction event consumer was experiencing severe lag under burst load. Switched to manual asynchronous commit and configured a dead letter queue (DLQ) for malformed records. Detailed technical notes on partition rebalance. Trace reference: DC-1008.
```

#### Gold Chunk `scale:doc:00008:c3` — grade `1` — source `email`

```text
[EMAIL] Optimize Kafka consumer group commit interval and backpressure (DC-1008)
Section 4: Resolves ticket DC-1008: transaction event consumer was experiencing severe lag under burst load. Switched to manual asynchronous commit and configured a dead letter queue (DLQ) for malformed records. Detailed technical notes on backpressure. Trace reference: DC-1008.
```

### qv2-id-04

- **Query ID:** `qv2-id-04`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_10` (groups: `group_engineering`)
- **Query Text:** DC-1009

#### Gold Chunk `scale:doc:00009:c0` — grade `2` — source `github`

```text
[GITHUB] Mitigate cache stampede on employee directory endpoints (DC-1009)
Section 1: Resolves ticket DC-1009: database CPU spiked when popular cache keys expired simultaneously. Implemented XFetch probabilistic early expiration and added jitter to cache TTLs. Detailed technical notes on Redis. Trace reference: DC-1009.
```

#### Gold Chunk `scale:doc:00009:c1` — grade `1` — source `github`

```text
[GITHUB] Mitigate cache stampede on employee directory endpoints (DC-1009)
Section 2: Resolves ticket DC-1009: database CPU spiked when popular cache keys expired simultaneously. Implemented XFetch probabilistic early expiration and added jitter to cache TTLs. Detailed technical notes on caching. Trace reference: DC-1009.
```

#### Gold Chunk `scale:doc:00009:c2` — grade `1` — source `github`

```text
[GITHUB] Mitigate cache stampede on employee directory endpoints (DC-1009)
Section 3: Resolves ticket DC-1009: database CPU spiked when popular cache keys expired simultaneously. Implemented XFetch probabilistic early expiration and added jitter to cache TTLs. Detailed technical notes on cache stampede. Trace reference: DC-1009.
```

#### Gold Chunk `scale:doc:00009:c3` — grade `1` — source `github`

```text
[GITHUB] Mitigate cache stampede on employee directory endpoints (DC-1009)
Section 4: Resolves ticket DC-1009: database CPU spiked when popular cache keys expired simultaneously. Implemented XFetch probabilistic early expiration and added jitter to cache TTLs. Detailed technical notes on probabilistic early expiration. Trace reference: DC-1009.
```

### qv2-id-05

- **Query ID:** `qv2-id-05`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_01` (groups: `group_engineering`, `group_finance`, `group_security`)
- **Query Text:** DC-1017

#### Gold Chunk `scale:doc:00017:c0` — grade `2` — source `email`

```text
[EMAIL] Implement silent token refresh with rotation grace period (DC-1017)
Section 1: Resolves ticket DC-1017: users were being logged out unexpectedly when tokens expired. Introduced single-use refresh token rotation with a 30-second grace window to handle concurrent API requests cleanly. Detailed technical notes on authentication. Trace reference: DC-1017.
```

#### Gold Chunk `scale:doc:00017:c1` — grade `1` — source `email`

```text
[EMAIL] Implement silent token refresh with rotation grace period (DC-1017)
Section 2: Resolves ticket DC-1017: users were being logged out unexpectedly when tokens expired. Introduced single-use refresh token rotation with a 30-second grace window to handle concurrent API requests cleanly. Detailed technical notes on JWT. Trace reference: DC-1017.
```

#### Gold Chunk `scale:doc:00017:c2` — grade `1` — source `email`

```text
[EMAIL] Implement silent token refresh with rotation grace period (DC-1017)
Section 3: Resolves ticket DC-1017: users were being logged out unexpectedly when tokens expired. Introduced single-use refresh token rotation with a 30-second grace window to handle concurrent API requests cleanly. Detailed technical notes on refresh token. Trace reference: DC-1017.
```

#### Gold Chunk `scale:doc:00017:c3` — grade `1` — source `email`

```text
[EMAIL] Implement silent token refresh with rotation grace period (DC-1017)
Section 4: Resolves ticket DC-1017: users were being logged out unexpectedly when tokens expired. Introduced single-use refresh token rotation with a 30-second grace window to handle concurrent API requests cleanly. Detailed technical notes on session expiry. Trace reference: DC-1017.
```

### qv2-id-10

- **Query ID:** `qv2-id-10`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** CVE-2026-4410

#### Gold Chunk `doc:email:security@company.internal:msg-cve-4410:c0` — grade `2` — source `email`

```text
Security bulletin for CVE-2026-4410: upgrade xmlsec1 base image to 1.3.7 across all SAML SSO identity consumers before Friday 18:00 UTC.
```

### qv2-id-11

- **Query ID:** `qv2-id-11`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** HNSW_EF_SEARCH_OVERRIDE

#### Gold Chunk `doc:slack:C08SRCH:thread:1700000011.000100:c0` — grade `2` — source `slack`

```text
Set HNSW_EF_SEARCH_OVERRIDE=120 inside PostgreSQL transactions when tenant catalog density exceeds 50k chunks per namespace.
```

### qv2-id-12

- **Query ID:** `qv2-id-12`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** X-Billing-Hmac-V2

#### Gold Chunk `doc:github:company/billing-hooks:pr:308:c0` — grade `2` — source `github`

```text
WebhookVerifierMiddleware validates the X-Billing-Hmac-V2 SHA-256 digest header with a 300-second replay timestamp tolerance.
```

### qv2-id-13

- **Query ID:** `qv2-id-13`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** ReconcileSettlementBatch

#### Gold Chunk `doc:github:company/payout-worker:pr:519:c0` — grade `2` — source `github`

```text
ReconcileSettlementBatch RPC now persists checkpoint tokens per merchant shard so interrupted nightly runs resume cleanly.
```

### qv2-id-14

- **Query ID:** `qv2-id-14`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_01` (groups: `group_engineering`, `group_finance`, `group_security`)
- **Query Text:** RFC-0042

#### Gold Chunk `doc:email:arch@company.internal:msg-rfc-0042:c0` — grade `2` — source `email`

```text
Architecture board approved RFC-0042 adopting envelope KMS data keys rotated quarterly per enterprise organization.
```

### qv2-id-17

- **Query ID:** `qv2-id-17`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_10` (groups: `group_engineering`)
- **Query Text:** pg_stat_statements_track_all

#### Gold Chunk `doc:email:dba@company.internal:msg-pgstat-17:c0` — grade `2` — source `email`

```text
Staging RDS parameter group now sets pg_stat_statements_track_all=on with max=10000 to profile stored function subqueries.
```

### qv2-id-19

- **Query ID:** `qv2-id-19`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** SEC-904

#### Gold Chunk `doc:slack:C04SEC:thread:1700000019.000100:c0` — grade `2` — source `slack`

```text
SEC-904 completed emergency rotation of HashiCorp Vault audit webhook bearer token for restricted compliance logs.
```

### qv2-id-20

- **Query ID:** `qv2-id-20`
- **Query Type:** `exact_identifier`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** BILL-312

#### Gold Chunk `doc:email:billing@company.internal:msg-bill-312:c0` — grade `2` — source `email`

```text
BILL-312 resolved negative invoice tax rounding when annual enterprise seats downgrade mid-quarter.
```

### qv2-sem-01

- **Query ID:** `qv2-sem-01`
- **Query Type:** `semantic`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** reloading TLS identity certs in envoy without dropping live proxy sockets

#### Gold Chunk `doc:github:company/mesh-proxy:pr:601:c0` — grade `2` — source `github`

```text
Configured xDS Secret Discovery Service filesystem watch on sidecar containers so updated leaf credentials hot-swap safely during active HTTP2 traffic.
```

### qv2-sem-02

- **Query ID:** `qv2-sem-02`
- **Query Type:** `semantic`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** preventing postgres catalog exhaustion from aged unvacuumed transaction counters

#### Gold Chunk `doc:email:dba@company.internal:msg-sem-02:c0` — grade `2` — source `email`

```text
Lowered autovacuum_freeze_max_age to 150000000 and boosted maintenance_work_mem so append-only ledger partitions clean ancient tuple XIDs ahead of wraparound shutdown.
```

### qv2-sem-03

- **Query ID:** `qv2-sem-03`
- **Query Type:** `semantic`
- **Identity:** `employee_10` (groups: `group_engineering`)
- **Query Text:** kubernetes cluster drain stalling during worker AMI upgrades

#### Gold Chunk `doc:slack:C06K8S:thread:1700000103.000100:c0` — grade `2` — source `slack`

```text
A PodDisruptionBudget setting minAvailable equal to replicas=1 blocked EC2 cordoning; switching policy to maxUnavailable=25% unblocked rolling ASG replacements.
```

### qv2-sem-04

- **Query ID:** `qv2-sem-04`
- **Query Type:** `semantic`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** hardening native smartphone OAuth sign-in against redirect URI hijacking

#### Gold Chunk `doc:github:company/auth-portal:pr:604:c0` — grade `2` — source `github`

```text
Enforced RFC 7636 PKCE SHA-256 code_challenge exchanges for iOS and Android flows so intercepted callback tokens cannot be swapped for session grants.
```

### qv2-sem-05

- **Query ID:** `qv2-sem-05`
- **Query Type:** `semantic`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** trimming bloated cloud blob storage bills caused by stalled chunked transfers

#### Gold Chunk `doc:email:finops@company.internal:msg-sem-05:c0` — grade `2` — source `email`

```text
Added a 7-day S3 lifecycle rule calling AbortIncompleteMultipartUpload across export buckets, reclaiming 18TB of orphaned partial binary segments.
```

### qv2-sem-06

- **Query ID:** `qv2-sem-06`
- **Query Type:** `semantic`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** avoiding concurrent IaC mutations corrupting shared provisioning state files

#### Gold Chunk `doc:github:company/tf-modules:pr:606:c0` — grade `2` — source `github`

```text
Provisioned DynamoDB table tf-remote-locks as a conditional mutex so overlapping CI pipeline applies serialize instead of overwriting production VPC manifests.
```

### qv2-sem-07

- **Query ID:** `qv2-sem-07`
- **Query Type:** `semantic`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** stopping mobile network retries from double charging customer credit cards

#### Gold Chunk `doc:slack:C0123PAY:thread:1700000107.000100:c0` — grade `2` — source `slack`

```text
Persisted client-supplied Idempotency-Key hashes with unique DB constraints inside checkout settlement so flaky cellular POST submissions return cached receipts.
```

### qv2-sem-08

- **Query ID:** `qv2-sem-08`
- **Query Type:** `semantic`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** cancelling slow downstream RPC work once ingress gateway timing budget expires

#### Gold Chunk `doc:github:company/rpc-mesh:pr:608:c0` — grade `2` — source `github`

```text
Wired gRPC Context deadline forwarding into Python asyncio workers so caller disconnects abort orphan SQL queries before exhausting backend threads.
```

### qv2-sem-09

- **Query ID:** `qv2-sem-09`
- **Query Type:** `semantic`
- **Identity:** `employee_10` (groups: `group_engineering`)
- **Query Text:** routing five percent of edge visitors onto canary kubernetes cluster

#### Gold Chunk `doc:email:sre@company.internal:msg-sem-09:c0` — grade `2` — source `email`

```text
Configured weighted DNS aliases splitting ingress traffic 95/5 across standby regions during Tuesday rollout verification before promoting primary cutover.
```

### qv2-sem-10

- **Query ID:** `qv2-sem-10`
- **Query Type:** `semantic`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** guaranteeing broker event emission whenever relational order commit succeeds

#### Gold Chunk `doc:github:company/order-service:pr:610:c0` — grade `2` — source `github`

```text
Adopted transactional outbox pattern inserting domain payloads inside the Postgres ACID unit before Debezium relays messages asynchronously toward Kafka topics.
```

### qv2-sem-11

- **Query ID:** `qv2-sem-11`
- **Query Type:** `semantic`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** tolerating slight NTP clock drift between auth issuer and API verifier

#### Gold Chunk `doc:slack:C04SEC:thread:1700000111.000100:c0` — grade `2` — source `slack`

```text
Configured PyJWT decode leeway=30 seconds on verification middleware after container hypervisor virtualization skew rejected freshly minted bearer assertions.
```

### qv2-sem-12

- **Query ID:** `qv2-sem-12`
- **Query Type:** `semantic`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** eliminating tail latency spikes right after autoscaler boots cold API replicas

#### Gold Chunk `doc:github:company/workmesh-api:pr:612:c0` — grade `2` — source `github`

```text
Added lifespan pre-warming loop opening minimum psycopg pool sockets and priming sentence embeddings before marking Kubernetes /ready green.
```

### qv2-sem-13

- **Query ID:** `qv2-sem-13`
- **Query Type:** `semantic`
- **Identity:** `employee_01` (groups: `group_engineering`, `group_finance`, `group_security`)
- **Query Text:** coordinating nightly table partitioning cron jobs across redundant scheduler instances

#### Gold Chunk `doc:email:dba@company.internal:msg-sem-13:c0` — grade `2` — source `email`

```text
Wrapped monthly child partition DDL creation inside pg_try_advisory_xact_lock keyed by deterministic CRC32 hashes so multi-region schedulers never race.
```

### qv2-sem-14

- **Query ID:** `qv2-sem-14`
- **Query Type:** `semantic`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** preventing stale user settings flashes immediately following profile updates

#### Gold Chunk `doc:slack:C0123PAY:thread:1700000114.000100:c0` — grade `2` — source `slack`

```text
Stored short-lived Redis session LSN watermarks for 5 seconds after POST mutations to pin subsequent GET lookups onto primary PostgreSQL instances.
```

### qv2-sem-16

- **Query ID:** `qv2-sem-16`
- **Query Type:** `semantic`
- **Identity:** `employee_10` (groups: `group_engineering`)
- **Query Text:** avoiding container OOM kills under sudden monitoring span bursts

#### Gold Chunk `doc:slack:C10OBS:thread:1700000116.000100:c0` — grade `2` — source `slack`

```text
Switched OpenTelemetry exporter queue to fixed capacity=4096 with drop-newest backpressure instead of unbounded heap allocation during upstream outages.
```

### qv2-sem-17

- **Query ID:** `qv2-sem-17`
- **Query Type:** `semantic`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** diagnosing sluggish RocksDB LSM range scans following heavy row deletions

#### Gold Chunk `doc:email:storage@company.internal:msg-sem-17:c0` — grade `2` — source `email`

```text
Mass TTL purges left millions of tombstone markers choking SSTable iterators; scheduling periodic single-delete compaction restored normal iterator speed.
```

### qv2-sem-19

- **Query ID:** `qv2-sem-19`
- **Query Type:** `semantic`
- **Identity:** `employee_01` (groups: `group_engineering`, `group_finance`, `group_security`)
- **Query Text:** automatically halting bad releases when error budget burn crosses threshold

#### Gold Chunk `doc:slack:C06K8S:thread:1700000119.000100:c0` — grade `2` — source `slack`

```text
Integrated Prometheus AnalysisTemplate checking HTTP 5xx ratio <= 1% over 5-minute canary steps to trigger instant Argo Rollouts revert.
```

### qv2-sem-20

- **Query ID:** `qv2-sem-20`
- **Query Type:** `semantic`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** speeding up deep page navigation on massive million-row audit UI

#### Gold Chunk `doc:github:company/audit-api:pr:620:c0` — grade `2` — source `github`

```text
Eliminated slow SQL OFFSET 50000 table scans by adopting opaque tuple cursor tokens filtering directly against indexed timestamp keys.
```

### qv2-multi-02

- **Query ID:** `qv2-multi-02`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** What Slack mitigation stopped the billing webhook storm and which commit added signature caching?

#### Gold Chunk `doc:github:company/billing-hooks:commit:7c2201aa91f0:c0` — grade `2` — source `github`

```text
Commit 7c2201aa91f0 fixes V2-102 root cause by adding a 15-minute local LRU cache for webhook public verification certificates.
```

#### Gold Chunk `doc:slack:C0123PAY:thread:1700000202.000100:c0` — grade `2` — source `slack`

```text
V2-102 triage notes: paused retry DLQ consumer and enabled Cloudflare edge rate limit of 50 req/s on /webhooks/billing to stop downstream CPU saturation.
```

### qv2-multi-03

- **Query ID:** `qv2-multi-03`
- **Query Type:** `multi_source`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** Which email approved raising statement_timeout for analytics exports and which PR configured the dedicated role?

#### Gold Chunk `doc:email:dba@company.internal:msg-v2-103:c0` — grade `2` — source `email`

```text
V2-103 decision email: DBA lead approved raising PostgreSQL statement_timeout from 15s to 120s strictly for read-replica role analytics_ro during quarterly close.
```

#### Gold Chunk `doc:github:company/dba-terraform:pr:703:c0` — grade `2` — source `github`

```text
Pull Request #703 implements V2-103 via Terraform postgresql_role setting statement_timeout='120s' exclusively on the reporting replica user analytics_ro.
```

### qv2-multi-05

- **Query ID:** `qv2-multi-05`
- **Query Type:** `multi_source`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** What vendor email warned about TLS 1.1 deprecation and which PR removed legacy ciphers?

#### Gold Chunk `doc:email:partner@gateway.com:msg-v2-105:c0` — grade `2` — source `email`

```text
V2-105 vendor notice: Acquiring bank sandbox and production endpoints disable TLS 1.0/1.1 and CBC cipher suites permanently on November 30.
```

#### Gold Chunk `doc:github:company/ingress-mesh:pr:705:c0` — grade `2` — source `github`

```text
Pull Request #705 resolves V2-105 by bumping ALB SSLPolicy to ELBSecurityPolicy-TLS13-1-2-2021-06 and stripping legacy CBC ciphers.
```

### qv2-multi-06

- **Query ID:** `qv2-multi-06`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** How did Slack triage explain the Redis OOM spike and which PR enforced maxmemory-policy?

#### Gold Chunk `doc:github:company/cache-infra:pr:706:c0` — grade `2` — source `github`

```text
Pull Request #706 addresses V2-106 by updating Terraform ElastiCache parameter group to maxmemory-policy=allkeys-lfu with reserved-memory-percent=15.
```

#### Gold Chunk `doc:slack:C08SRCH:thread:1700000206.000100:c0` — grade `2` — source `slack`

```text
V2-106 incident root cause: cache node ran with noeviction policy, failing all SET writes when embedding feature vectors filled 16GB RAM.
```

### qv2-multi-07

- **Query ID:** `qv2-multi-07`
- **Query Type:** `multi_source`
- **Identity:** `employee_01` (groups: `group_engineering`, `group_finance`, `group_security`)
- **Query Text:** What email outlined compliance retention for audit logs and which PR implemented S3 Object Lock?

#### Gold Chunk `doc:email:legal@company.internal:msg-v2-107:c0` — grade `2` — source `email`

```text
V2-107 compliance directive: immutable write-once-read-many audit archives must be tamper-proof for 2,555 days to pass Type II audit review.
```

#### Gold Chunk `doc:github:company/audit-archive:pr:707:c0` — grade `2` — source `github`

```text
Pull Request #707 satisfies V2-107 by enabling S3 Object Lock in COMPLIANCE mode with default 2555-day retention on audit-worm-archive.
```

### qv2-multi-09

- **Query ID:** `qv2-multi-09`
- **Query Type:** `multi_source`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** Which email flagged invoice PDF memory exhaustion and what commit streamed renders to disk?

#### Gold Chunk `doc:email:finance.ops@company.internal:msg-v2-109:c0` — grade `2` — source `email`

```text
V2-109 incident report: large enterprise accounts with 12,000 line items exceeded 2GB container memory while buffering PDF bytes in RAM.
```

#### Gold Chunk `doc:github:company/invoice-renderer:commit:44b19c0d82e1:c0` — grade `2` — source `github`

```text
Commit 44b19c0d82e1 resolves V2-109 by streaming WeasyPrint chunk writes to SpooledTemporaryFile instead of BytesIO buffers.
```

### qv2-multi-10

- **Query ID:** `qv2-multi-10`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** What Slack debate settled 15 concurrent workers for backpressure and which PR implemented Retry-After?

#### Gold Chunk `doc:github:company/workmesh:pr:710:c0` — grade `2` — source `github`

```text
Pull Request #710 implements V2-110 via ConcurrencyLimiter(max_concurrent=15) returning HTTP 503 Service Unavailable with Retry-After: 1.
```

#### Gold Chunk `doc:slack:C10OBS:thread:1700000210.000100:c0` — grade `2` — source `slack`

```text
V2-110 load test finding: throughput peaked around 15 active queries (~38 req/s) before CPU embedding contention degraded p95 sharply.
```

### qv2-multi-11

- **Query ID:** `qv2-multi-11`
- **Query Type:** `multi_source`
- **Identity:** `employee_04` (groups: `group_engineering`)
- **Query Text:** What did Slack report about Kafka consumer rebalance storms and which PR increased session.timeout.ms?

#### Gold Chunk `doc:github:company/event-workers:pr:711:c0` — grade `2` — source `github`

```text
Pull Request #711 fixes V2-111 by switching to CooperativeStickyAssignor and bumping Kafka session.timeout.ms to 45000.
```

#### Gold Chunk `doc:slack:C09DBA:thread:1700000211.000100:c0` — grade `2` — source `slack`

```text
V2-111 incident chat: long GC pauses over 12s triggered continuous coordinator evictions in the settlement consumer group every 4 minutes.
```

### qv2-multi-13

- **Query ID:** `qv2-multi-13`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** What architectural change did Slack propose for email source IDs and what PR fixed duplicate message rows?

#### Gold Chunk `doc:github:company/email-connector:pr:713:c0` — grade `2` — source `github`

```text
Pull Request #713 repairs V2-113 in EmailFixtureAdapter by setting source_id to per-mailbox message record ID.
```

#### Gold Chunk `doc:slack:C08SRCH:thread:1700000213.000100:c0` — grade `2` — source `slack`

```text
V2-113 diagnosis: when two employees receive the same email, both Sent and INBOX copies share one RFC Message-ID, colliding on unique (source_type, source_id).
```

### qv2-multi-14

- **Query ID:** `qv2-multi-14`
- **Query Type:** `multi_source`
- **Identity:** `employee_06` (groups: `group_engineering`, `group_finance`)
- **Query Text:** Which email flagged Stripe idempotency header truncation and which commit preserved full UUID length?

#### Gold Chunk `doc:email:payments@company.internal:msg-v2-114:c0` — grade `2` — source `email`

```text
V2-114 postmortem summary: legacy VARCHAR(24) column truncated 36-char UUID idempotency keys, collapsing distinct refund calls into cached responses.
```

#### Gold Chunk `doc:github:company/payment-service:commit:b119f30e2a4c:c0` — grade `2` — source `github`

```text
Commit b119f30e2a4c fixes V2-114 with schema migration widening payment_attempts.idempotency_key from 24 to 64 characters.
```

### qv2-multi-15

- **Query ID:** `qv2-multi-15`
- **Query Type:** `multi_source`
- **Identity:** `employee_05` (groups: `group_engineering`, `group_security`)
- **Query Text:** What Slack finding triggered removing HS256 default secret fallback and what PR aborted prod boot?

#### Gold Chunk `doc:github:company/workmesh:pr:715:c0` — grade `2` — source `github`

```text
Pull Request #715 implements V2-115 in config.py Settings validator, raising ValueError if prod lacks a 32+ char non-default JWT_SECRET.
```

#### Gold Chunk `doc:slack:C04SEC:thread:1700000215.000100:c0` — grade `2` — source `slack`

```text
V2-115 security review: leaving a default signing key on Settings allowed valid token forgery if staging env vars were omitted in production.
```

### qv2-multi-16

- **Query ID:** `qv2-multi-16`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** What did Slack say about pgvector HNSW iterative_scan and what email summarized the 1% access recall gain?

#### Gold Chunk `doc:email:search@company.internal:msg-v2-116:c0` — grade `2` — source `email`

```text
V2-116 verification email: 1% tenant Recall@5 improved from 80.7% (4.63 results) to 90.7% (5.00/5 results) with zero unauthorized chunk leaks.
```

#### Gold Chunk `doc:slack:C08SRCH:thread:1700000216.000100:c0` — grade `2` — source `slack`

```text
V2-116 Slack thread: enabling SET LOCAL hnsw.iterative_scan = 'relaxed_order' with exact fallback prevents empty results when users can read only 1% of corpus.
```

### qv2-multi-18

- **Query ID:** `qv2-multi-18`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** What Slack incident discussed orphaned Postgres advisory locks after pod SIGKILL and what PR added timeouts?

#### Gold Chunk `doc:github:company/workmesh:pr:718:c0` — grade `2` — source `github`

```text
Pull Request #718 resolves V2-118 by adding lease_expires_at TTL expiration and monotonic lease_token fencing to sync lease acquisition.
```

#### Gold Chunk `doc:slack:C09DBA:thread:1700000218.000100:c0` — grade `2` — source `slack`

```text
V2-118 incident log: OOMKilled ingestion worker left sync_state status=SYNCING locked indefinitely until manual admin reset ran.
```

### qv2-multi-19

- **Query ID:** `qv2-multi-19`
- **Query Type:** `multi_source`
- **Identity:** `employee_01` (groups: `group_engineering`, `group_finance`, `group_security`)
- **Query Text:** Which email summarized the SAML clock skew outage and which Slack thread confirmed the 60s assertion window?

#### Gold Chunk `doc:email:security@company.internal:msg-v2-119:c0` — grade `2` — source `email`

```text
V2-119 incident summary: 18-second clock offset between Okta IdP and EU ingress caused NotBefore assertion failures for 14% of logins.
```

#### Gold Chunk `doc:slack:C04SEC:thread:1700000219.000100:c0` — grade `2` — source `slack`

```text
V2-119 Slack update: deployed 60-second NotBefore clock skew tolerance on SAML SP assertion consumer; login error rate dropped to 0.0%.
```

### qv2-multi-20

- **Query ID:** `qv2-multi-20`
- **Query Type:** `multi_source`
- **Identity:** `employee_42` (groups: `group_engineering`, `group_backend`)
- **Query Text:** What did Slack say about non-root UID 10001 Docker permissions and which PR baked model weights at build time?

#### Gold Chunk `doc:github:company/workmesh:pr:720:c0` — grade `2` — source `github`

```text
Pull Request #720 satisfies V2-120 using multi-stage python:3.11-slim Dockerfile running as user workmesh (UID 10001) with pre-baked HF_HOME weights.
```

#### Gold Chunk `doc:slack:C06K8S:thread:1700000220.000100:c0` — grade `2` — source `slack`

```text
V2-120 Slack alert: cluster admission controller now requires non-root UID 10001 and blocks outbound runtime model downloads in production pods.
```
