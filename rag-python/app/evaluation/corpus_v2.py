"""Deterministic v2 evaluation corpus extension and query generator.

Adds 55 distinct domain documents (~95 chunks) alongside the 10,000-chunk scale corpus
with real entity-graph links across GitHub, Slack, and Email, plus diverse ACLs.
This prevents template duplication from masking semantic and multi-source retrieval quality.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.chunking.models import CanonicalChunk
from app.connectors.common.models import (
    AclReference,
    PrincipalType,
    RawSourceItem,
    SourceType,
)
from app.embeddings.base import EmbeddingProvider
from app.embeddings.factory import get_embedding_provider
from app.graph.models import Entity, EntityType, Relationship, RelationshipType
from app.indexing.repository import PostgresKnowledgeRepository
from app.normalization.models import CanonicalDocument

# Named evaluation identities aligned with simulated groups in scale_benchmark.py
EVAL_USERS: dict[str, list[str]] = {
    "employee_42": ["group_engineering", "group_backend"],
    "employee_01": ["group_engineering", "group_finance", "group_security"],
    "employee_04": ["group_engineering"],
    "employee_05": ["group_engineering", "group_security"],
    "employee_06": ["group_engineering", "group_finance"],
    "employee_10": ["group_engineering"],
}

# 15 unique exact-identifier scenarios (complemented by 5 scale DC-* tickets = 20 total)
EXACT_ID_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "qv2-id-06",
        "query": "ERR_MTLS_HANDSHAKE_495",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C04SEC:thread:1700000001.000100",
        "url": "https://company.slack.com/archives/C04SEC/p1700000001000100",
        "title": "#edge-security: Resolving ERR_MTLS_HANDSHAKE_495 on partner ingress",
        "chunks": [
            "Alert triggered in edge proxy: ERR_MTLS_HANDSHAKE_495 spikes whenever partner leaf certificates lack ExtendedKeyUsage clientAuth.",
            "Mitigation step for ERR_MTLS_HANDSHAKE_495: upload intermediate bundle to truststore-prod-v4 and drain unhealthy Envoy pods.",
        ],
        "principal": ("GROUP", "group_security"),
        "user_id": "employee_05",
    },
    {
        "id": "qv2-id-07",
        "query": "9f3e21ab4c8d",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/ledger-core:commit:9f3e21ab4c8d",
        "url": "https://github.com/company/ledger-core/commit/9f3e21ab4c8d",
        "title": "Commit 9f3e21ab4c8d: fix double-entry rounding drift in FX legs",
        "chunks": [
            "Commit 9f3e21ab4c8d updates MultiCurrencyPostingEngine to accumulate sub-cent remainders before posting rounding adjustment entries.",
        ],
        "principal": ("GROUP", "group_finance"),
        "user_id": "employee_06",
    },
    {
        "id": "qv2-id-08",
        "query": "SlidingWindowRateLimiter",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/edge-gateway:pr:742",
        "url": "https://github.com/company/edge-gateway/pull/742",
        "title": "PR #742: Introduce SlidingWindowRateLimiter for tenant API quotas",
        "chunks": [
            "PR #742 adds SlidingWindowRateLimiter using atomic Lua scripts to enforce per-tenant burst quotas across API gateway replicas.",
            "Benchmark tests for SlidingWindowRateLimiter verify 0.4ms p99 overhead at 12,000 requests/sec.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-id-09",
        "query": "FIN-418",
        "source_type": "EMAIL",
        "doc_id": "doc:email:finance.ops@company.internal:msg-fin-418",
        "url": "https://mail.company.internal/mail/finance.ops/inbox/msg-fin-418",
        "title": "Email: FIN-418 Q4 Stripe Payout Reconciliation Variance",
        "chunks": [
            "Ticket FIN-418 tracks a $14,220 settlement timing delta between European SEPA batch clearing and nightly ledger ingestion.",
        ],
        "principal": ("GROUP", "group_finance"),
        "user_id": "employee_01",
    },
    {
        "id": "qv2-id-10",
        "query": "CVE-2026-4410",
        "source_type": "EMAIL",
        "doc_id": "doc:email:security@company.internal:msg-cve-4410",
        "url": "https://mail.company.internal/mail/security/inbox/msg-cve-4410",
        "title": "Email: Urgent Advisory CVE-2026-4410 XML Signature Wrapping Patch",
        "chunks": [
            "Security bulletin for CVE-2026-4410: upgrade xmlsec1 base image to 1.3.7 across all SAML SSO identity consumers before Friday 18:00 UTC.",
        ],
        "principal": ("GROUP", "group_security"),
        "user_id": "employee_05",
    },
    {
        "id": "qv2-id-11",
        "query": "HNSW_EF_SEARCH_OVERRIDE",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C08SRCH:thread:1700000011.000100",
        "url": "https://company.slack.com/archives/C08SRCH/p1700000011000100",
        "title": "#search-infra: Tuning HNSW_EF_SEARCH_OVERRIDE for 99th percentile recall",
        "chunks": [
            "Set HNSW_EF_SEARCH_OVERRIDE=120 inside PostgreSQL transactions when tenant catalog density exceeds 50k chunks per namespace.",
        ],
        "principal": ("GROUP", "group_backend"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-id-12",
        "query": "X-Billing-Hmac-V2",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/billing-hooks:pr:308",
        "url": "https://github.com/company/billing-hooks/pull/308",
        "title": "PR #308: Enforce X-Billing-Hmac-V2 signature verification on webhooks",
        "chunks": [
            "WebhookVerifierMiddleware validates the X-Billing-Hmac-V2 SHA-256 digest header with a 300-second replay timestamp tolerance.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_04",
    },
    {
        "id": "qv2-id-13",
        "query": "ReconcileSettlementBatch",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/payout-worker:pr:519",
        "url": "https://github.com/company/payout-worker/pull/519",
        "title": "PR #519: Add idempotent cursor resume to ReconcileSettlementBatch RPC",
        "chunks": [
            "ReconcileSettlementBatch RPC now persists checkpoint tokens per merchant shard so interrupted nightly runs resume cleanly.",
        ],
        "principal": ("GROUP", "group_finance"),
        "user_id": "employee_06",
    },
    {
        "id": "qv2-id-14",
        "query": "RFC-0042",
        "source_type": "EMAIL",
        "doc_id": "doc:email:arch@company.internal:msg-rfc-0042",
        "url": "https://mail.company.internal/mail/arch/sent/msg-rfc-0042",
        "title": "Email: RFC-0042 Tenant-Isolated Encryption Key Hierarchy Approval",
        "chunks": [
            "Architecture board approved RFC-0042 adopting envelope KMS data keys rotated quarterly per enterprise organization.",
        ],
        "principal": ("GROUP", "group_security"),
        "user_id": "employee_01",
    },
    {
        "id": "qv2-id-15",
        "query": "idx_ledger_entries_created",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C09DBA:thread:1700000015.000100",
        "url": "https://company.slack.com/archives/C09DBA/p1700000015000100",
        "title": "#dba-ops: Creating idx_ledger_entries_created concurrently without table locks",
        "chunks": [
            "Build idx_ledger_entries_created using CREATE INDEX CONCURRENTLY during low traffic and monitor pg_stat_progress_create_index.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_04",
    },
    {
        "id": "qv2-id-16",
        "query": "workmesh_queue_saturation_ratio",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C10OBS:thread:1700000016.000100",
        "url": "https://company.slack.com/archives/C10OBS/p1700000016000100",
        "title": "#observability: Alert rule thresholds on workmesh_queue_saturation_ratio",
        "chunks": [
            "Page on-call SRE if workmesh_queue_saturation_ratio stays above 0.85 for 3 consecutive evaluation windows in Prometheus.",
        ],
        "principal": ("GROUP", "group_backend"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-id-17",
        "query": "pg_stat_statements_track_all",
        "source_type": "EMAIL",
        "doc_id": "doc:email:dba@company.internal:msg-pgstat-17",
        "url": "https://mail.company.internal/mail/dba/inbox/msg-pgstat-17",
        "title": "Email: Enabling pg_stat_statements_track_all in staging clusters",
        "chunks": [
            "Staging RDS parameter group now sets pg_stat_statements_track_all=on with max=10000 to profile stored function subqueries.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_10",
    },
    {
        "id": "qv2-id-18",
        "query": "OPS-772",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/infra-runbooks:pr:89",
        "url": "https://github.com/company/infra-runbooks/pull/89",
        "title": "PR #89: Document OPS-772 CoreDNS nodelocal cache sysctl tuning",
        "chunks": [
            "OPS-772 fixed intermittent DNS lookup timeouts under EKS burst autoscaling by raising nf_conntrack_max to 262144.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_04",
    },
    {
        "id": "qv2-id-19",
        "query": "SEC-904",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C04SEC:thread:1700000019.000100",
        "url": "https://company.slack.com/archives/C04SEC/p1700000019000100",
        "title": "#edge-security: Private SEC-904 Vault audit sink token rotation",
        "chunks": [
            "SEC-904 completed emergency rotation of HashiCorp Vault audit webhook bearer token for restricted compliance logs.",
        ],
        "principal": ("USER", "employee_05"),
        "user_id": "employee_05",
    },
    {
        "id": "qv2-id-20",
        "query": "BILL-312",
        "source_type": "EMAIL",
        "doc_id": "doc:email:billing@company.internal:msg-bill-312",
        "url": "https://mail.company.internal/mail/billing/sent/msg-bill-312",
        "title": "Email: BILL-312 Private Proration Credit Memo Fix",
        "chunks": [
            "BILL-312 resolved negative invoice tax rounding when annual enterprise seats downgrade mid-quarter.",
        ],
        "principal": ("USER", "employee_42"),
        "user_id": "employee_42",
    },
]

# 20 Semantic paraphrase scenarios.
# CRITICAL RULE: Every query shares <= 1 content word with EVERY gold chunk in its qrels!
SEMANTIC_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "qv2-sem-01",
        "query": "reloading TLS identity certs in envoy without dropping live proxy sockets",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/mesh-proxy:pr:601",
        "url": "https://github.com/company/mesh-proxy/pull/601",
        "title": "Secret Discovery Service file watcher for zero-downtime mTLS rotation",
        "chunks": [
            "Configured xDS Secret Discovery Service filesystem watch on sidecar containers so updated leaf credentials hot-swap safely during active HTTP2 traffic.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-sem-02",
        "query": "preventing postgres catalog exhaustion from aged unvacuumed transaction counters",
        "source_type": "EMAIL",
        "doc_id": "doc:email:dba@company.internal:msg-sem-02",
        "url": "https://mail.company.internal/mail/dba/inbox/msg-sem-02",
        "title": "PostgreSQL Maintenance Runbook Update",
        "chunks": [
            "Lowered autovacuum_freeze_max_age to 150000000 and boosted maintenance_work_mem so append-only ledger partitions clean ancient tuple XIDs ahead of wraparound shutdown.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_04",
    },
    {
        "id": "qv2-sem-03",
        "query": "kubernetes cluster drain stalling during worker AMI upgrades",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C06K8S:thread:1700000103.000100",
        "url": "https://company.slack.com/archives/C06K8S/p1700000103000100",
        "title": "#k8s-platform: Eviction guard deadlock resolution",
        "chunks": [
            "A PodDisruptionBudget setting minAvailable equal to replicas=1 blocked EC2 cordoning; switching policy to maxUnavailable=25% unblocked rolling ASG replacements.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_10",
    },
    {
        "id": "qv2-sem-04",
        "query": "hardening native smartphone OAuth sign-in against redirect URI hijacking",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/auth-portal:pr:604",
        "url": "https://github.com/company/auth-portal/pull/604",
        "title": "Mandate S256 verifier challenge for public clients",
        "chunks": [
            "Enforced RFC 7636 PKCE SHA-256 code_challenge exchanges for iOS and Android flows so intercepted callback tokens cannot be swapped for session grants.",
        ],
        "principal": ("GROUP", "group_security"),
        "user_id": "employee_05",
    },
    {
        "id": "qv2-sem-05",
        "query": "trimming bloated cloud blob storage bills caused by stalled chunked transfers",
        "source_type": "EMAIL",
        "doc_id": "doc:email:finops@company.internal:msg-sem-05",
        "url": "https://mail.company.internal/mail/finops/inbox/msg-sem-05",
        "title": "Weekly Infrastructure Cost Optimization Brief",
        "chunks": [
            "Added a 7-day S3 lifecycle rule calling AbortIncompleteMultipartUpload across export buckets, reclaiming 18TB of orphaned partial binary segments.",
        ],
        "principal": ("GROUP", "group_finance"),
        "user_id": "employee_06",
    },
    {
        "id": "qv2-sem-06",
        "query": "avoiding concurrent IaC mutations corrupting shared provisioning state files",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/tf-modules:pr:606",
        "url": "https://github.com/company/tf-modules/pull/606",
        "title": "Enable atomic lease backend for remote infrastructure automation",
        "chunks": [
            "Provisioned DynamoDB table tf-remote-locks as a conditional mutex so overlapping CI pipeline applies serialize instead of overwriting production VPC manifests.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-sem-07",
        "query": "stopping mobile network retries from double charging customer credit cards",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C0123PAY:thread:1700000107.000100",
        "url": "https://company.slack.com/archives/C0123PAY/p1700000107000100",
        "title": "#payments-engineering: Replay-safe checkout capture design",
        "chunks": [
            "Persisted client-supplied Idempotency-Key hashes with unique DB constraints inside checkout settlement so flaky cellular POST submissions return cached receipts.",
        ],
        "principal": ("GROUP", "group_backend"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-sem-08",
        "query": "cancelling slow downstream RPC work once ingress gateway timing budget expires",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/rpc-mesh:pr:608",
        "url": "https://github.com/company/rpc-mesh/pull/608",
        "title": "Propagate context timeout metadata across microservice hops",
        "chunks": [
            "Wired gRPC Context deadline forwarding into Python asyncio workers so caller disconnects abort orphan SQL queries before exhausting backend threads.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_04",
    },
    {
        "id": "qv2-sem-09",
        "query": "routing five percent of edge visitors onto canary kubernetes cluster",
        "source_type": "EMAIL",
        "doc_id": "doc:email:sre@company.internal:msg-sem-09",
        "url": "https://mail.company.internal/mail/sre/sent/msg-sem-09",
        "title": "Gradual Blue-Green Cutover Procedure",
        "chunks": [
            "Configured weighted DNS aliases splitting ingress traffic 95/5 across standby regions during Tuesday rollout verification before promoting primary cutover.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_10",
    },
    {
        "id": "qv2-sem-10",
        "query": "guaranteeing broker event emission whenever relational order commit succeeds",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/order-service:pr:610",
        "url": "https://github.com/company/order-service/pull/610",
        "title": "Reliable CDC publication via local durable staging table",
        "chunks": [
            "Adopted transactional outbox pattern inserting domain payloads inside the Postgres ACID unit before Debezium relays messages asynchronously toward Kafka topics.",
        ],
        "principal": ("GROUP", "group_backend"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-sem-11",
        "query": "tolerating slight NTP clock drift between auth issuer and API verifier",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C04SEC:thread:1700000111.000100",
        "url": "https://company.slack.com/archives/C04SEC/p1700000111000100",
        "title": "#edge-security: Eliminating false token expiry rejections",
        "chunks": [
            "Configured PyJWT decode leeway=30 seconds on verification middleware after container hypervisor virtualization skew rejected freshly minted bearer assertions.",
        ],
        "principal": ("GROUP", "group_security"),
        "user_id": "employee_05",
    },
    {
        "id": "qv2-sem-12",
        "query": "eliminating tail latency spikes right after autoscaler boots cold API replicas",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/workmesh-api:pr:612",
        "url": "https://github.com/company/workmesh-api/pull/612",
        "title": "Eagerly initialize DB connections during container startup probe",
        "chunks": [
            "Added lifespan pre-warming loop opening minimum psycopg pool sockets and priming sentence embeddings before marking Kubernetes /ready green.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_04",
    },
    {
        "id": "qv2-sem-13",
        "query": "coordinating nightly table partitioning cron jobs across redundant scheduler instances",
        "source_type": "EMAIL",
        "doc_id": "doc:email:dba@company.internal:msg-sem-13",
        "url": "https://mail.company.internal/mail/dba/sent/msg-sem-13",
        "title": "Deterministic DDL Execution Serialization",
        "chunks": [
            "Wrapped monthly child partition DDL creation inside pg_try_advisory_xact_lock keyed by deterministic CRC32 hashes so multi-region schedulers never race.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_01",
    },
    {
        "id": "qv2-sem-14",
        "query": "preventing stale user settings flashes immediately following profile updates",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C0123PAY:thread:1700000114.000100",
        "url": "https://company.slack.com/archives/C0123PAY/p1700000114000100",
        "title": "#payments-engineering: Read-your-own-writes consistency fix",
        "chunks": [
            "Stored short-lived Redis session LSN watermarks for 5 seconds after POST mutations to pin subsequent GET lookups onto primary PostgreSQL instances.",
        ],
        "principal": ("GROUP", "group_backend"),
        "user_id": "employee_42",
    },
    {
        "id": "qv2-sem-15",
        "query": "blocking malicious injected browser scripts with cryptographic header per request",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/web-console:pr:615",
        "url": "https://github.com/company/web-console/pull/615",
        "title": "Strict Content-Security-Policy enforcement in frontend gateway",
        "chunks": [
            "Generated random Base64 nonces per HTTP response paired with CSP script-src directives so unauthorized inline DOM XSS payloads fail execution.",
        ],
        "principal": ("GROUP", "group_security"),
        "user_id": "employee_05",
    },
    {
        "id": "qv2-sem-16",
        "query": "avoiding container OOM kills under sudden monitoring span bursts",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C10OBS:thread:1700000116.000100",
        "url": "https://company.slack.com/archives/C10OBS/p1700000116000100",
        "title": "#observability: Collector bounded buffer policy",
        "chunks": [
            "Switched OpenTelemetry exporter queue to fixed capacity=4096 with drop-newest backpressure instead of unbounded heap allocation during upstream outages.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_10",
    },
    {
        "id": "qv2-sem-17",
        "query": "diagnosing sluggish RocksDB LSM range scans following heavy row deletions",
        "source_type": "EMAIL",
        "doc_id": "doc:email:storage@company.internal:msg-sem-17",
        "url": "https://mail.company.internal/mail/storage/inbox/msg-sem-17",
        "title": "Embedded KV Engine Compaction Findings",
        "chunks": [
            "Mass TTL purges left millions of tombstone markers choking SSTable iterators; scheduling periodic single-delete compaction restored normal iterator speed.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_04",
    },
    {
        "id": "qv2-sem-18",
        "query": "offloading multi-hundred megabyte billing CSV archives away from API server workers",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/export-api:pr:618",
        "url": "https://github.com/company/export-api/pull/618",
        "title": "Asynchronous signed object redirect for large report downloads",
        "chunks": [
            "Replaced streaming FastAPI FileResponse endpoints with 15-minute KMS-authorized pre-signed S3 URLs so Python ASGI workers stay responsive.",
        ],
        "principal": ("GROUP", "group_finance"),
        "user_id": "employee_06",
    },
    {
        "id": "qv2-sem-19",
        "query": "automatically halting bad releases when error budget burn crosses threshold",
        "source_type": "SLACK",
        "doc_id": "doc:slack:C06K8S:thread:1700000119.000100",
        "url": "https://company.slack.com/archives/C06K8S/p1700000119000100",
        "title": "#k8s-platform: Argo Rollouts automated abort webhook",
        "chunks": [
            "Integrated Prometheus AnalysisTemplate checking HTTP 5xx ratio <= 1% over 5-minute canary steps to trigger instant Argo Rollouts revert.",
        ],
        "principal": ("GROUP", "group_engineering"),
        "user_id": "employee_01",
    },
    {
        "id": "qv2-sem-20",
        "query": "speeding up deep page navigation on massive million-row audit UI",
        "source_type": "GITHUB",
        "doc_id": "doc:github:company/audit-api:pr:620",
        "url": "https://github.com/company/audit-api/pull/620",
        "title": "Keyset seek pagination over (created_at, id) composite B-tree index",
        "chunks": [
            "Eliminated slow SQL OFFSET 50000 table scans by adopting opaque tuple cursor tokens filtering directly against indexed timestamp keys.",
        ],
        "principal": ("GROUP", "group_backend"),
        "user_id": "employee_42",
    },
]

# 20 Multi-Source scenarios: each has two distinct documents across two different sources,
# linked in the entity graph via a shared V2 ticket entity.
MULTI_SOURCE_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "qv2-multi-01",
        "ticket": "V2-101",
        "query": "Why did we switch session cookies to SameSite=Lax and which PR implemented it?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C04SEC:thread:1700000201.000100",
            "entity_id": "slack:C04SEC:1700000201.000100",
            "url": "https://company.slack.com/archives/C04SEC/p1700000201000100",
            "title": "#edge-security: V2-101 SSO callback breakage with strict cookie attribute",
            "text": "V2-101 postmortem in Slack: SameSite=Strict dropped session cookies during third-party IdP redirects; security agreed switching to SameSite=Lax preserves CSRF protection while fixing SSO logins.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/auth-gateway:pr:701",
            "entity_id": "pr:company/auth-gateway:701",
            "url": "https://github.com/company/auth-gateway/pull/701",
            "title": "PR #701 (V2-101): Set SameSite=Lax on session cookie builder",
            "text": "Pull Request #701 resolves V2-101 by updating SessionCookieFactory.build() to emit SameSite=Lax with HttpOnly and Secure flags enabled across all gateways.",
        },
    },
    {
        "id": "qv2-multi-02",
        "ticket": "V2-102",
        "query": "What Slack mitigation stopped the billing webhook storm and which commit added signature caching?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C0123PAY:thread:1700000202.000100",
            "entity_id": "slack:C0123PAY:1700000202.000100",
            "url": "https://company.slack.com/archives/C0123PAY/p1700000202000100",
            "title": "#payments-engineering: V2-102 Billing webhook storm triage",
            "text": "V2-102 triage notes: paused retry DLQ consumer and enabled Cloudflare edge rate limit of 50 req/s on /webhooks/billing to stop downstream CPU saturation.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/billing-hooks:commit:7c2201aa91f0",
            "entity_id": "commit:company/billing-hooks:7c2201aa91f0",
            "url": "https://github.com/company/billing-hooks/commit/7c2201aa91f0",
            "title": "Commit 7c2201aa (V2-102): Cache JWKS signature verification keys",
            "text": "Commit 7c2201aa91f0 fixes V2-102 root cause by adding a 15-minute local LRU cache for webhook public verification certificates.",
        },
    },
    {
        "id": "qv2-multi-03",
        "ticket": "V2-103",
        "query": "Which email approved raising statement_timeout for analytics exports and which PR configured the dedicated role?",
        "user_id": "employee_06",
        "principal": ("GROUP", "group_finance"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:dba@company.internal:msg-v2-103",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/dba/sent/msg-v2-103",
            "title": "Email: V2-103 Approval for analytics_ro 120s statement_timeout",
            "text": "V2-103 decision email: DBA lead approved raising PostgreSQL statement_timeout from 15s to 120s strictly for read-replica role analytics_ro during quarterly close.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/dba-terraform:pr:703",
            "entity_id": "pr:company/dba-terraform:703",
            "url": "https://github.com/company/dba-terraform/pull/703",
            "title": "PR #703 (V2-103): Configure analytics_ro Postgres role parameters",
            "text": "Pull Request #703 implements V2-103 via Terraform postgresql_role setting statement_timeout='120s' exclusively on the reporting replica user analytics_ro.",
        },
    },
    {
        "id": "qv2-multi-04",
        "ticket": "V2-104",
        "query": "Why did Slack engineers pick Zstandard over Gzip for trace compression and what PR rolled it out?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_backend"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C10OBS:thread:1700000204.000100",
            "entity_id": "slack:C10OBS:1700000204.000100",
            "url": "https://company.slack.com/archives/C10OBS/p1700000204000100",
            "title": "#observability: V2-104 OTLP Zstandard vs Gzip benchmark thread",
            "text": "V2-104 benchmark consensus: Zstandard level 3 reduced trace egress bandwidth 42% over Gzip while cutting collector CPU overhead by 35%.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/otel-config:pr:704",
            "entity_id": "pr:company/otel-config:704",
            "url": "https://github.com/company/otel-config/pull/704",
            "title": "PR #704 (V2-104): Switch OTLP gRPC exporter compression to zstd",
            "text": "Pull Request #704 completes V2-104 by configuring compression: zstd on all production OpenTelemetry Collector otlp exporter pipelines.",
        },
    },
    {
        "id": "qv2-multi-05",
        "ticket": "V2-105",
        "query": "What vendor email warned about TLS 1.1 deprecation and which PR removed legacy ciphers?",
        "user_id": "employee_05",
        "principal": ("GROUP", "group_security"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:partner@gateway.com:msg-v2-105",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/security/inbox/msg-v2-105",
            "title": "Email: V2-105 Mandatory Partner Gateway TLS 1.1 End-of-Life Notice",
            "text": "V2-105 vendor notice: Acquiring bank sandbox and production endpoints disable TLS 1.0/1.1 and CBC cipher suites permanently on November 30.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/ingress-mesh:pr:705",
            "entity_id": "pr:company/ingress-mesh:705",
            "url": "https://github.com/company/ingress-mesh/pull/705",
            "title": "PR #705 (V2-105): Enforce TLS 1.2+ minimum protocol and AEAD ciphers",
            "text": "Pull Request #705 resolves V2-105 by bumping ALB SSLPolicy to ELBSecurityPolicy-TLS13-1-2-2021-06 and stripping legacy CBC ciphers.",
        },
    },
    {
        "id": "qv2-multi-06",
        "ticket": "V2-106",
        "query": "How did Slack triage explain the Redis OOM spike and which PR enforced maxmemory-policy?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C08SRCH:thread:1700000206.000100",
            "entity_id": "slack:C08SRCH:1700000206.000100",
            "url": "https://company.slack.com/archives/C08SRCH/p1700000206000100",
            "title": "#search-infra: V2-106 Redis cluster OOM incident analysis",
            "text": "V2-106 incident root cause: cache node ran with noeviction policy, failing all SET writes when embedding feature vectors filled 16GB RAM.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/cache-infra:pr:706",
            "entity_id": "pr:company/cache-infra:706",
            "url": "https://github.com/company/cache-infra/pull/706",
            "title": "PR #706 (V2-106): Set Redis maxmemory-policy allkeys-lfu",
            "text": "Pull Request #706 addresses V2-106 by updating Terraform ElastiCache parameter group to maxmemory-policy=allkeys-lfu with reserved-memory-percent=15.",
        },
    },
    {
        "id": "qv2-multi-07",
        "ticket": "V2-107",
        "query": "What email outlined compliance retention for audit logs and which PR implemented S3 Object Lock?",
        "user_id": "employee_01",
        "principal": ("GROUP", "group_security"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:legal@company.internal:msg-v2-107",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/legal/sent/msg-v2-107",
            "title": "Email: V2-107 SOC2 WORM Audit Retention Mandate (7 Years)",
            "text": "V2-107 compliance directive: immutable write-once-read-many audit archives must be tamper-proof for 2,555 days to pass Type II audit review.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/audit-archive:pr:707",
            "entity_id": "pr:company/audit-archive:707",
            "url": "https://github.com/company/audit-archive/pull/707",
            "title": "PR #707 (V2-107): Enable S3 Object Lock COMPLIANCE mode on audit bucket",
            "text": "Pull Request #707 satisfies V2-107 by enabling S3 Object Lock in COMPLIANCE mode with default 2555-day retention on audit-worm-archive.",
        },
    },
    {
        "id": "qv2-multi-08",
        "ticket": "V2-108",
        "query": "What schema migration blocker was raised in Slack for pgvector 384 dims and which PR updated the SQL?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C08SRCH:thread:1700000208.000100",
            "entity_id": "slack:C08SRCH:1700000208.000100",
            "url": "https://company.slack.com/archives/C08SRCH/p1700000208000100",
            "title": "#search-infra: V2-108 Stopping zero-padding vector(1536) bloat",
            "text": "V2-108 discussion: padding 384-dim MiniLM outputs to 1536 zeroes inflated HNSW index memory 4x; agreed migrating schema directly to vector(384).",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/workmesh:pr:708",
            "entity_id": "pr:company/workmesh:708",
            "url": "https://github.com/company/workmesh/pull/708",
            "title": "PR #708 (V2-108): Alter chunks.embedding column to vector(384)",
            "text": "Pull Request #708 delivers V2-108 by migrating DDL schema chunks.embedding to vector(384) and removing legacy zero-padding code.",
        },
    },
    {
        "id": "qv2-multi-09",
        "ticket": "V2-109",
        "query": "Which email flagged invoice PDF memory exhaustion and what commit streamed renders to disk?",
        "user_id": "employee_06",
        "principal": ("GROUP", "group_finance"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:finance.ops@company.internal:msg-v2-109",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/finance.ops/inbox/msg-v2-109",
            "title": "Email: V2-109 Monthly enterprise invoice generator OOM crash",
            "text": "V2-109 incident report: large enterprise accounts with 12,000 line items exceeded 2GB container memory while buffering PDF bytes in RAM.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/invoice-renderer:commit:44b19c0d82e1",
            "entity_id": "commit:company/invoice-renderer:44b19c0d82e1",
            "url": "https://github.com/company/invoice-renderer/commit/44b19c0d82e1",
            "title": "Commit 44b19c0d (V2-109): Stream invoice PDF pages via SpooledTemporaryFile",
            "text": "Commit 44b19c0d82e1 resolves V2-109 by streaming WeasyPrint chunk writes to SpooledTemporaryFile instead of BytesIO buffers.",
        },
    },
    {
        "id": "qv2-multi-10",
        "ticket": "V2-110",
        "query": "What Slack debate settled 15 concurrent workers for backpressure and which PR implemented Retry-After?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_backend"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C10OBS:thread:1700000210.000100",
            "entity_id": "slack:C10OBS:1700000210.000100",
            "url": "https://company.slack.com/archives/C10OBS/p1700000210000100",
            "title": "#observability: V2-110 Setting concurrency limit to 15 workers",
            "text": "V2-110 load test finding: throughput peaked around 15 active queries (~38 req/s) before CPU embedding contention degraded p95 sharply.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/workmesh:pr:710",
            "entity_id": "pr:company/workmesh:710",
            "url": "https://github.com/company/workmesh/pull/710",
            "title": "PR #710 (V2-110): Shed excess search load with 503 and Retry-After: 1",
            "text": "Pull Request #710 implements V2-110 via ConcurrencyLimiter(max_concurrent=15) returning HTTP 503 Service Unavailable with Retry-After: 1.",
        },
    },
    {
        "id": "qv2-multi-11",
        "ticket": "V2-111",
        "query": "What did Slack report about Kafka consumer rebalance storms and which PR increased session.timeout.ms?",
        "user_id": "employee_04",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C09DBA:thread:1700000211.000100",
            "entity_id": "slack:C09DBA:1700000211.000100",
            "url": "https://company.slack.com/archives/C09DBA/p1700000211000100",
            "title": "#dba-ops: V2-111 Kafka consumer group stop-the-world rebalance loop",
            "text": "V2-111 incident chat: long GC pauses over 12s triggered continuous coordinator evictions in the settlement consumer group every 4 minutes.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/event-workers:pr:711",
            "entity_id": "pr:company/event-workers:711",
            "url": "https://github.com/company/event-workers/pull/711",
            "title": "PR #711 (V2-111): Tune session.timeout.ms=45000 and max.poll.interval.ms",
            "text": "Pull Request #711 fixes V2-111 by switching to CooperativeStickyAssignor and bumping Kafka session.timeout.ms to 45000.",
        },
    },
    {
        "id": "qv2-multi-12",
        "ticket": "V2-112",
        "query": "What email warned about NAT gateway port exhaustion and which PR switched to VPC endpoints?",
        "user_id": "employee_10",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:sre@company.internal:msg-v2-112",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/sre/inbox/msg-v2-112",
            "title": "Email: V2-112 SNAT Ephemeral Port Exhaustion in us-east-1a",
            "text": "V2-112 incident email: High S3/ECR pull concurrency saturated the 55k ephemeral NAT Gateway ports, causing external TLS connect timeouts.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/aws-network:pr:712",
            "entity_id": "pr:company/aws-network:712",
            "url": "https://github.com/company/aws-network/pull/712",
            "title": "PR #712 (V2-112): Route S3 and ECR traffic via AWS PrivateLink VPC endpoints",
            "text": "Pull Request #712 solves V2-112 by adding Gateway VPC endpoint for S3 and Interface endpoints for ecr.dkr to bypass NAT Gateways.",
        },
    },
    {
        "id": "qv2-multi-13",
        "ticket": "V2-113",
        "query": "What architectural change did Slack propose for email source IDs and what PR fixed duplicate message rows?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C08SRCH:thread:1700000213.000100",
            "entity_id": "slack:C08SRCH:1700000213.000100",
            "url": "https://company.slack.com/archives/C08SRCH/p1700000213000100",
            "title": "#search-infra: V2-113 UniqueViolation on shared RFC Message-ID across mailboxes",
            "text": "V2-113 diagnosis: when two employees receive the same email, both Sent and INBOX copies share one RFC Message-ID, colliding on unique (source_type, source_id).",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/email-connector:pr:713",
            "entity_id": "pr:company/email-connector:713",
            "url": "https://github.com/company/email-connector/pull/713",
            "title": "PR #713 (V2-113): Key source_id by unique fixture msg id instead of RFC Message-ID",
            "text": "Pull Request #713 repairs V2-113 in EmailFixtureAdapter by setting source_id to per-mailbox message record ID.",
        },
    },
    {
        "id": "qv2-multi-14",
        "ticket": "V2-114",
        "query": "Which email flagged Stripe idempotency header truncation and which commit preserved full UUID length?",
        "user_id": "employee_06",
        "principal": ("GROUP", "group_finance"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:payments@company.internal:msg-v2-114",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/payments/inbox/msg-v2-114",
            "title": "Email: V2-114 Stripe Idempotency Key Collision on Refund Batch",
            "text": "V2-114 postmortem summary: legacy VARCHAR(24) column truncated 36-char UUID idempotency keys, collapsing distinct refund calls into cached responses.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/payment-service:commit:b119f30e2a4c",
            "entity_id": "commit:company/payment-service:b119f30e2a4c",
            "url": "https://github.com/company/payment-service/commit/b119f30e2a4c",
            "title": "Commit b119f30e (V2-114): Widen idempotency_key to VARCHAR(64)",
            "text": "Commit b119f30e2a4c fixes V2-114 with schema migration widening payment_attempts.idempotency_key from 24 to 64 characters.",
        },
    },
    {
        "id": "qv2-multi-15",
        "ticket": "V2-115",
        "query": "What Slack finding triggered removing HS256 default secret fallback and what PR aborted prod boot?",
        "user_id": "employee_05",
        "principal": ("GROUP", "group_security"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C04SEC:thread:1700000215.000100",
            "entity_id": "slack:C04SEC:1700000215.000100",
            "url": "https://company.slack.com/archives/C04SEC/p1700000215000100",
            "title": "#edge-security: V2-115 Fail-closed JWT_SECRET startup check",
            "text": "V2-115 security review: leaving a default signing key on Settings allowed valid token forgery if staging env vars were omitted in production.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/workmesh:pr:715",
            "entity_id": "pr:company/workmesh:715",
            "url": "https://github.com/company/workmesh/pull/715",
            "title": "PR #715 (V2-115): Abort startup when prod JWT_SECRET is default or <32 chars",
            "text": "Pull Request #715 implements V2-115 in config.py Settings validator, raising ValueError if prod lacks a 32+ char non-default JWT_SECRET.",
        },
    },
    {
        "id": "qv2-multi-16",
        "ticket": "V2-116",
        "query": "What did Slack say about pgvector HNSW iterative_scan and what email summarized the 1% access recall gain?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C08SRCH:thread:1700000216.000100",
            "entity_id": "slack:C08SRCH:1700000216.000100",
            "url": "https://company.slack.com/archives/C08SRCH/p1700000216000100",
            "title": "#search-infra: V2-116 Fixing low-access HNSW post-filter starvation",
            "text": "V2-116 Slack thread: enabling SET LOCAL hnsw.iterative_scan = 'relaxed_order' with exact fallback prevents empty results when users can read only 1% of corpus.",
        },
        "source_b": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:search@company.internal:msg-v2-116",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/search/sent/msg-v2-116",
            "title": "Email: V2-116 1% Tenant Recall@5 Verification Report",
            "text": "V2-116 verification email: 1% tenant Recall@5 improved from 80.7% (4.63 results) to 90.7% (5.00/5 results) with zero unauthorized chunk leaks.",
        },
    },
    {
        "id": "qv2-multi-17",
        "ticket": "V2-117",
        "query": "Why did SRE ask in email to add Prometheus histogram buckets under 50ms and which PR exported /metrics?",
        "user_id": "employee_04",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:sre@company.internal:msg-v2-117",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/sre/inbox/msg-v2-117",
            "title": "Email: V2-117 Fine-grained SLO histogram buckets for API latency",
            "text": "V2-117 SRE request: coarse 100ms buckets hide sub-50ms degradation during warm cache hits; add 10ms and 25ms boundaries to latency histograms.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/workmesh:pr:717",
            "entity_id": "pr:company/workmesh:717",
            "url": "https://github.com/company/workmesh/pull/717",
            "title": "PR #717 (V2-117): Export /metrics Prometheus latency quantiles and buckets",
            "text": "Pull Request #717 resolves V2-117 by exposing workmesh_http_request_duration_seconds buckets including 0.01 and 0.025 on GET /metrics.",
        },
    },
    {
        "id": "qv2-multi-18",
        "ticket": "V2-118",
        "query": "What Slack incident discussed orphaned Postgres advisory locks after pod SIGKILL and what PR added timeouts?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_backend"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C09DBA:thread:1700000218.000100",
            "entity_id": "slack:C09DBA:1700000218.000100",
            "url": "https://company.slack.com/archives/C09DBA/p1700000218000100",
            "title": "#dba-ops: V2-118 Stale connector sync lease after worker SIGKILL",
            "text": "V2-118 incident log: OOMKilled ingestion worker left sync_state status=SYNCING locked indefinitely until manual admin reset ran.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/workmesh:pr:718",
            "entity_id": "pr:company/workmesh:718",
            "url": "https://github.com/company/workmesh/pull/718",
            "title": "PR #718 (V2-118): Add lease_expires_at fencing tokens to sync_state",
            "text": "Pull Request #718 resolves V2-118 by adding lease_expires_at TTL expiration and monotonic lease_token fencing to sync lease acquisition.",
        },
    },
    {
        "id": "qv2-multi-19",
        "ticket": "V2-119",
        "query": "Which email summarized the SAML clock skew outage and which Slack thread confirmed the 60s assertion window?",
        "user_id": "employee_01",
        "principal": ("GROUP", "group_security"),
        "source_a": {
            "source_type": "EMAIL",
            "doc_id": "doc:email:security@company.internal:msg-v2-119",
            "entity_id": None,
            "url": "https://mail.company.internal/mail/security/sent/msg-v2-119",
            "title": "Email: V2-119 Okta SAML Assertion NotBefore Rejection Summary",
            "text": "V2-119 incident summary: 18-second clock offset between Okta IdP and EU ingress caused NotBefore assertion failures for 14% of logins.",
        },
        "source_b": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C04SEC:thread:1700000219.000100",
            "entity_id": "slack:C04SEC:1700000219.000100",
            "url": "https://company.slack.com/archives/C04SEC/p1700000219000100",
            "title": "#edge-security: V2-119 Confirmed 60-second SAML skew window live",
            "text": "V2-119 Slack update: deployed 60-second NotBefore clock skew tolerance on SAML SP assertion consumer; login error rate dropped to 0.0%.",
        },
    },
    {
        "id": "qv2-multi-20",
        "ticket": "V2-120",
        "query": "What did Slack say about non-root UID 10001 Docker permissions and which PR baked model weights at build time?",
        "user_id": "employee_42",
        "principal": ("GROUP", "group_engineering"),
        "source_a": {
            "source_type": "SLACK",
            "doc_id": "doc:slack:C06K8S:thread:1700000220.000100",
            "entity_id": "slack:C06K8S:1700000220.000100",
            "url": "https://company.slack.com/archives/C06K8S/p1700000220000100",
            "title": "#k8s-platform: V2-120 PodSecurity Restricted runAsNonRoot enforcement",
            "text": "V2-120 Slack alert: cluster admission controller now requires non-root UID 10001 and blocks outbound runtime model downloads in production pods.",
        },
        "source_b": {
            "source_type": "GITHUB",
            "doc_id": "doc:github:company/workmesh:pr:720",
            "entity_id": "pr:company/workmesh:720",
            "url": "https://github.com/company/workmesh/pull/720",
            "title": "PR #720 (V2-120): Multi-stage Dockerfile with UID 10001 and cached MiniLM weights",
            "text": "Pull Request #720 satisfies V2-120 using multi-stage python:3.11-slim Dockerfile running as user workmesh (UID 10001) with pre-baked HF_HOME weights.",
        },
    },
]

# First 5 exact-identifier queries target existing 10k-scale documents across varied ACL tiers
SCALE_EXACT_ID_QUERIES: list[dict[str, Any]] = [
    {
        "id": "qv2-id-01",
        "category": "exact_identifier",
        "query": "DC-1000",
        "user_id": "employee_42",
        "group_ids": EVAL_USERS["employee_42"],
        "qrels": {
            "scale:doc:00000:c0": 2,
            "scale:doc:00000:c1": 1,
            "scale:doc:00000:c2": 1,
            "scale:doc:00000:c3": 1,
        },
    },
    {
        "id": "qv2-id-02",
        "category": "exact_identifier",
        "query": "DC-1006",
        "user_id": "employee_06",
        "group_ids": EVAL_USERS["employee_06"],
        "qrels": {
            "scale:doc:00006:c0": 2,
            "scale:doc:00006:c1": 1,
            "scale:doc:00006:c2": 1,
            "scale:doc:00006:c3": 1,
        },
    },
    {
        "id": "qv2-id-03",
        "category": "exact_identifier",
        "query": "DC-1008",
        "user_id": "employee_05",
        "group_ids": EVAL_USERS["employee_05"],
        "qrels": {
            "scale:doc:00008:c0": 2,
            "scale:doc:00008:c1": 1,
            "scale:doc:00008:c2": 1,
            "scale:doc:00008:c3": 1,
        },
    },
    {
        "id": "qv2-id-04",
        "category": "exact_identifier",
        "query": "DC-1009",
        "user_id": "employee_10",
        "group_ids": EVAL_USERS["employee_10"],
        "qrels": {
            "scale:doc:00009:c0": 2,
            "scale:doc:00009:c1": 1,
            "scale:doc:00009:c2": 1,
            "scale:doc:00009:c3": 1,
        },
    },
    {
        "id": "qv2-id-05",
        "category": "exact_identifier",
        "query": "DC-1017",
        "user_id": "employee_01",
        "group_ids": EVAL_USERS["employee_01"],
        "qrels": {
            "scale:doc:00017:c0": 2,
            "scale:doc:00017:c1": 1,
            "scale:doc:00017:c2": 1,
            "scale:doc:00017:c3": 1,
        },
    },
]


def _make_acl(doc_id: str, chunk_ids: list[str], principal: tuple[str, str]) -> list[AclReference]:
    p_type = PrincipalType(principal[0])
    p_id = principal[1]
    acls = [
        AclReference(
            resource_type="DOCUMENT",
            resource_id=doc_id,
            principal_type=p_type,
            principal_id=p_id,
            permission="READ",
        )
    ]
    for cid in chunk_ids:
        acls.append(
            AclReference(
                resource_type="CHUNK",
                resource_id=cid,
                principal_type=p_type,
                principal_id=p_id,
                permission="READ",
            )
        )
    return acls


def _content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


# 12 Denied-Identity scenarios: unprivileged or unauthorized identities querying restricted documents.
# Evaluates pushdown SQL ACL filtering to guarantee a 0.0% permission leak rate.
DENIED_IDENTITY_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "qv2-denied-01",
        "category": "denied_identity",
        "query": "FIN-418 payout reconciliation variance",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"doc:email:finance.ops@company.internal:msg-fin-418:c0": 2},
    },
    {
        "id": "qv2-denied-02",
        "category": "denied_identity",
        "query": "commit 9f3e21ab4c8d rounding drift FX legs",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"doc:github:company/ledger-core:commit:9f3e21ab4c8d:c0": 2},
    },
    {
        "id": "qv2-denied-03",
        "category": "denied_identity",
        "query": "ERR_MTLS_HANDSHAKE_495 leaf certificates",
        "user_id": "employee_06",
        "group_ids": ["group_engineering", "group_finance"],
        "qrels": {"doc:slack:C04SEC:thread:1700000001.000100:c0": 2},
    },
    {
        "id": "qv2-denied-04",
        "category": "denied_identity",
        "query": "CVE-2026-4410 XML signature wrapping patch",
        "user_id": "employee_06",
        "group_ids": ["group_engineering", "group_finance"],
        "qrels": {"doc:email:security@company.internal:msg-cve-4410:c0": 2},
    },
    {
        "id": "qv2-denied-05",
        "category": "denied_identity",
        "query": "ReconcileSettlementBatch checkpoint tokens",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:github:company/payout-worker:pr:519:c0": 2},
    },
    {
        "id": "qv2-denied-06",
        "category": "denied_identity",
        "query": "RFC-0042 tenant isolated encryption key hierarchy",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:email:arch@company.internal:msg-rfc-0042:c0": 2},
    },
    {
        "id": "qv2-denied-07",
        "category": "denied_identity",
        "query": "SEC-904 Vault audit sink bearer token rotation",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:slack:C04SEC:thread:1700000019.000100:c0": 2},
    },
    {
        "id": "qv2-denied-08",
        "category": "denied_identity",
        "query": "BILL-312 proration credit memo annual downgrade",
        "user_id": "employee_05",
        "group_ids": ["group_engineering", "group_security"],
        "qrels": {"doc:email:billing@company.internal:msg-bill-312:c0": 2},
    },
    {
        "id": "qv2-denied-09",
        "category": "denied_identity",
        "query": "V2-103 approval for analytics_ro statement_timeout",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"doc:email:dba@company.internal:msg-v2-103:c0": 2},
    },
    {
        "id": "qv2-denied-10",
        "category": "denied_identity",
        "query": "V2-105 TLS 1.1 deprecation mandatory vendor notice",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:email:partner@gateway.com:msg-v2-105:c0": 2},
    },
    {
        "id": "qv2-denied-11",
        "category": "denied_identity",
        "query": "V2-107 SOC2 WORM audit retention mandate 7 years",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"doc:email:legal@company.internal:msg-v2-107:c0": 2},
    },
    {
        "id": "qv2-denied-12",
        "category": "denied_identity",
        "query": "V2-109 enterprise monthly invoice generator OOM crash",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:email:finance.ops@company.internal:msg-v2-109:c0": 2},
    },
]

# 8 Link-Only scenarios: queries targeting entity relationships across tickets, PRs, Slack discussions, and commits.
LINK_ONLY_SCENARIOS: list[dict[str, Any]] = [
    {
        "id": "qv2-link-01",
        "category": "link_only",
        "query": "Which PR implemented ticket V2-101 session cookie fix?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:github:company/auth-gateway:pr:701:c0": 2},
    },
    {
        "id": "qv2-link-02",
        "category": "link_only",
        "query": "Which commit resolved ticket V2-102 billing webhook storm?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:github:company/billing-hooks:commit:7c2201aa91f0:c0": 2},
    },
    {
        "id": "qv2-link-03",
        "category": "link_only",
        "query": "Which PR configured the PostgreSQL role for V2-103 analytics exports?",
        "user_id": "employee_06",
        "group_ids": ["group_engineering", "group_finance"],
        "qrels": {"doc:github:company/dba-terraform:pr:703:c0": 2},
    },
    {
        "id": "qv2-link-04",
        "category": "link_only",
        "query": "What Slack discussion compared Zstandard against Gzip for V2-104?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:slack:C10OBS:thread:1700000204.000100:c0": 2},
    },
    {
        "id": "qv2-link-05",
        "category": "link_only",
        "query": "Which PR implemented TLS 1.2+ minimum protocol for ticket V2-105?",
        "user_id": "employee_05",
        "group_ids": ["group_engineering", "group_security"],
        "qrels": {"doc:github:company/ingress-mesh:pr:705:c0": 2},
    },
    {
        "id": "qv2-link-06",
        "category": "link_only",
        "query": "Which PR updated the ElastiCache parameter group for V2-106 Redis OOM?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:github:company/cache-infra:pr:706:c0": 2},
    },
    {
        "id": "qv2-link-07",
        "category": "link_only",
        "query": "Which PR enabled S3 Object Lock COMPLIANCE mode for V2-107 audit archive?",
        "user_id": "employee_01",
        "group_ids": ["group_engineering", "group_security"],
        "qrels": {"doc:github:company/audit-archive:pr:707:c0": 2},
    },
    {
        "id": "qv2-link-08",
        "category": "link_only",
        "query": "Which PR migrated the chunks embedding column to vector(384) for V2-108?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:github:company/workmesh:pr:708:c0": 2},
    },
]


def build_v2_queries() -> list[dict[str, Any]]:
    """Return the complete 80-query graded v2 evaluation suite."""
    queries: list[dict[str, Any]] = list(SCALE_EXACT_ID_QUERIES)

    for s in EXACT_ID_SCENARIOS:
        doc_id = s["doc_id"]
        qrels = {f"{doc_id}:c{idx}": (2 if idx == 0 else 1) for idx in range(len(s["chunks"]))}
        queries.append(
            {
                "id": s["id"],
                "category": "exact_identifier",
                "query": s["query"],
                "user_id": s["user_id"],
                "group_ids": EVAL_USERS[s["user_id"]],
                "qrels": qrels,
            }
        )

    for s in SEMANTIC_SCENARIOS:
        doc_id = s["doc_id"]
        qrels = {f"{doc_id}:c{idx}": (2 if idx == 0 else 1) for idx in range(len(s["chunks"]))}
        queries.append(
            {
                "id": s["id"],
                "category": "semantic",
                "query": s["query"],
                "user_id": s["user_id"],
                "group_ids": EVAL_USERS[s["user_id"]],
                "qrels": qrels,
            }
        )

    for s in MULTI_SOURCE_SCENARIOS:
        cid_a = f"{s['source_a']['doc_id']}:c0"
        cid_b = f"{s['source_b']['doc_id']}:c0"
        queries.append(
            {
                "id": s["id"],
                "category": "multi_source",
                "query": s["query"],
                "user_id": s["user_id"],
                "group_ids": EVAL_USERS[s["user_id"]],
                "required_sources": [
                    s["source_a"]["source_type"],
                    s["source_b"]["source_type"],
                ],
                "qrels": {cid_a: 2, cid_b: 2},
            }
        )

    for s in DENIED_IDENTITY_SCENARIOS:
        queries.append(dict(s))

    for s in LINK_ONLY_SCENARIOS:
        queries.append(dict(s))

    return queries


def export_queries_v2_jsonl(output_path: Path) -> Path:
    """Write data/evaluation/queries_v2.jsonl deterministically."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    queries = build_v2_queries()
    lines = [json.dumps(q) for q in queries]
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def build_v2_extension_records(
    embedder: EmbeddingProvider | None = None,
) -> tuple[
    list[CanonicalDocument],
    list[CanonicalChunk],
    list[AclReference],
    list[Entity],
    list[Relationship],
]:
    """Construct canonical documents, chunks, ACLs, entities, and relationships for v2 eval."""
    now = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)
    docs: list[CanonicalDocument] = []
    chunks: list[CanonicalChunk] = []
    acls: list[AclReference] = []
    entities: list[Entity] = []
    relationships: list[Relationship] = []

    raw_texts: list[str] = []
    pending_chunks: list[tuple[str, str, int, str]] = []

    for s in EXACT_ID_SCENARIOS + SEMANTIC_SCENARIOS:
        doc_id = s["doc_id"]
        src_rec_id = f"eval2:src:{s['id']}"
        full_content = "\n\n".join(s["chunks"])
        docs.append(
            CanonicalDocument(
                id=doc_id,
                source_record_id=src_rec_id,
                source_type=s["source_type"],
                title=s["title"],
                content=full_content,
                url=s["url"],
                author=s["user_id"],
                created_at=now,
                updated_at=now,
                metadata={"eval_v2": True, "scenario_id": s["id"]},
            )
        )
        chunk_ids: list[str] = []
        for idx, text in enumerate(s["chunks"]):
            cid = f"{doc_id}:c{idx}"
            chunk_ids.append(cid)
            pending_chunks.append((cid, doc_id, idx, text))
            raw_texts.append(text)
        acls.extend(_make_acl(doc_id, chunk_ids, s["principal"]))

    for s in MULTI_SOURCE_SCENARIOS:
        ticket_eid = f"ticket:{s['ticket']}"
        src_a = s["source_a"]
        src_b = s["source_b"]

        entities.append(
            Entity(
                id=ticket_eid,
                entity_type=EntityType.TICKET,
                name=s["ticket"],
                source_record_id=f"eval2:src:{s['id']}:a",
                metadata={"ticket_id": s["ticket"]},
            )
        )

        for suffix, part in (("a", src_a), ("b", src_b)):
            doc_id = part["doc_id"]
            src_rec_id = f"eval2:src:{s['id']}:{suffix}"
            docs.append(
                CanonicalDocument(
                    id=doc_id,
                    source_record_id=src_rec_id,
                    source_type=part["source_type"],
                    title=part["title"],
                    content=part["text"],
                    url=part["url"],
                    author=s["user_id"],
                    created_at=now,
                    updated_at=now,
                    metadata={"eval_v2": True, "scenario_id": s["id"], "ticket": s["ticket"]},
                )
            )
            cid = f"{doc_id}:c0"
            pending_chunks.append((cid, doc_id, 0, part["text"]))
            raw_texts.append(part["text"])
            acls.extend(_make_acl(doc_id, [cid], s["principal"]))

            if part.get("entity_id"):
                etype = (
                    EntityType.SLACK_THREAD
                    if part["source_type"] == "SLACK"
                    else EntityType.COMMIT
                    if ":commit:" in part["doc_id"]
                    else EntityType.PULL_REQUEST
                )
                entities.append(
                    Entity(
                        id=part["entity_id"],
                        entity_type=etype,
                        name=part["title"],
                        source_record_id=src_rec_id,
                        metadata={"doc_id": doc_id},
                    )
                )
                rel_type = (
                    RelationshipType.DISCUSSED_IN
                    if part["source_type"] == "SLACK"
                    else RelationshipType.IMPLEMENTED_BY
                )
                relationships.append(
                    Relationship(
                        source_entity_id=ticket_eid,
                        target_entity_id=part["entity_id"],
                        relationship_type=rel_type,
                        metadata={"scenario_id": s["id"]},
                    )
                )

        if src_a.get("entity_id") and src_b.get("entity_id"):
            relationships.append(
                Relationship(
                    source_entity_id=src_b["entity_id"],
                    target_entity_id=src_a["entity_id"],
                    relationship_type=RelationshipType.DISCUSSED_IN,
                    metadata={"scenario_id": s["id"]},
                )
            )

    embeddings: list[list[float] | None] = (
        list(embedder.embed_texts(raw_texts)) if embedder is not None else [None] * len(raw_texts)
    )
    for (cid, doc_id, idx, text), vec in zip(pending_chunks, embeddings):
        chunks.append(
            CanonicalChunk(
                id=cid,
                document_id=doc_id,
                chunk_index=idx,
                token_count=len(text.split()),
                content_hash=_content_hash(text),
                content=text,
                embedding=vec,
                created_at=now,
                metadata={"eval_v2": True},
            )
        )

    return docs, chunks, acls, entities, relationships


def seed_v2_evaluation_corpus(db_url: str, embedder: EmbeddingProvider | None = None) -> int:
    """Idempotently seed v2 evaluation documents, embeddings, ACLs, and graph links."""
    import psycopg

    if embedder is None:
        embedder = get_embedding_provider()

    docs, chunks, acls, entities, relationships = build_v2_extension_records(embedder=embedder)

    raw_records = [
        RawSourceItem(
            id=d.source_record_id,
            source_type=SourceType(d.source_type),
            source_id=d.id,
            source_url=d.url or "",
            title=d.title,
            author=d.author,
            raw_content=d.content,
            created_at=d.created_at,
            updated_at=d.updated_at,
            metadata=d.metadata,
        )
        for d in docs
    ]

    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            for uid, groups in EVAL_USERS.items():
                cur.execute(
                    "INSERT INTO users (id, email, full_name, role) VALUES (%s, %s, %s, %s) ON CONFLICT (id) DO NOTHING;",
                    (uid, f"{uid}@company.internal", f"Eval User {uid}", "ENGINEER"),
                )
                for gid in groups:
                    cur.execute(
                        "INSERT INTO groups (id, name, description) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING;",
                        (gid, gid, f"Group {gid}"),
                    )
                    cur.execute(
                        "INSERT INTO user_group_membership (user_id, group_id) VALUES (%s, %s) ON CONFLICT DO NOTHING;",
                        (uid, gid),
                    )
        conn.commit()

    repo = PostgresKnowledgeRepository(db_url)
    repo.save_source_records(raw_records)
    repo.save_documents(docs)
    repo.save_chunks(chunks)
    repo.save_acls(acls)
    repo.save_entities(entities)
    repo.save_relationships(relationships)

    with psycopg.connect(db_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("ANALYZE chunks;")
        cur.execute("ANALYZE documents;")
        cur.execute("ANALYZE acl_references;")

    return len(chunks)
