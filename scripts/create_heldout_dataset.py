"""Generate data/evaluation/queries_heldout_30.jsonl.

Held-out split of 30 brand-new queries (10 exact-id, 10 semantic, 10 multi-source)
that were never evaluated or used for parameter tuning.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_overlap import compute_overlap  # noqa: E402

HELDOUT_PATH = REPO_ROOT / "data" / "evaluation" / "queries_heldout_30.jsonl"

HELDOUT_QUERIES = [
    # -------------------------------------------------------------------------
    # 10 Exact Identifier Scenarios (Tickets, PRs, Error Codes, Commits)
    # -------------------------------------------------------------------------
    {
        "id": "heldout-id-01",
        "category": "exact_identifier",
        "query": "DC-1012",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"scale:doc:00012:c0": 2, "scale:doc:00012:c1": 1},
    },
    {
        "id": "heldout-id-02",
        "category": "exact_identifier",
        "query": "DC-1015",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"scale:doc:00015:c0": 2, "scale:doc:00015:c1": 1},
    },
    {
        "id": "heldout-id-03",
        "category": "exact_identifier",
        "query": "DC-1022",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"scale:doc:00022:c0": 2, "scale:doc:00022:c1": 1},
    },
    {
        "id": "heldout-id-04",
        "category": "exact_identifier",
        "query": "DC-1035",
        "user_id": "employee_06",
        "group_ids": ["group_engineering", "group_finance"],
        "qrels": {"scale:doc:00035:c0": 2, "scale:doc:00035:c1": 1},
    },
    {
        "id": "heldout-id-05",
        "category": "exact_identifier",
        "query": "DC-1042",
        "user_id": "employee_05",
        "group_ids": ["group_engineering", "group_security"],
        "qrels": {"scale:doc:00042:c0": 2, "scale:doc:00042:c1": 1},
    },
    {
        "id": "heldout-id-06",
        "category": "exact_identifier",
        "query": "DC-1055",
        "user_id": "employee_10",
        "group_ids": ["group_engineering"],
        "qrels": {"scale:doc:00055:c0": 2, "scale:doc:00055:c1": 1},
    },
    {
        "id": "heldout-id-07",
        "category": "exact_identifier",
        "query": "DC-1062",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"scale:doc:00062:c0": 2, "scale:doc:00062:c1": 1},
    },
    {
        "id": "heldout-id-08",
        "category": "exact_identifier",
        "query": "DC-1075",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"scale:doc:00075:c0": 2, "scale:doc:00075:c1": 1},
    },
    {
        "id": "heldout-id-09",
        "category": "exact_identifier",
        "query": "DC-1088",
        "user_id": "employee_06",
        "group_ids": ["group_engineering", "group_finance"],
        "qrels": {"scale:doc:00088:c0": 2, "scale:doc:00088:c1": 1},
    },
    {
        "id": "heldout-id-10",
        "category": "exact_identifier",
        "query": "DC-1095",
        "user_id": "employee_05",
        "group_ids": ["group_engineering", "group_security"],
        "qrels": {"scale:doc:00095:c0": 2, "scale:doc:00095:c1": 1},
    },

    # -------------------------------------------------------------------------
    # 10 Semantic Paraphrase Scenarios (Strictly <= 1 Content Word Overlap)
    # -------------------------------------------------------------------------
    {
        "id": "heldout-sem-01",
        "category": "semantic",
        "query": "mitigating ingress reverse-proxy authentication rejections from missing client key usage attributes",
        "user_id": "employee_05",
        "group_ids": ["group_engineering", "group_security"],
        "qrels": {"doc:slack:C04SEC:thread:1700000001.000100:c0": 2},
    },
    {
        "id": "heldout-sem-02",
        "category": "semantic",
        "query": "preventing sub-penny fractional calculation anomalies during conversion operations",
        "user_id": "employee_06",
        "group_ids": ["group_engineering", "group_finance"],
        "qrels": {"doc:github:company/ledger-core:commit:9f3e21ab4c8d:c0": 2},
    },
    {
        "id": "heldout-sem-03",
        "category": "semantic",
        "query": "investigating end-of-day bank settlement balance discrepancies in international accounts",
        "user_id": "employee_01",
        "group_ids": ["group_engineering", "group_finance", "group_security"],
        "qrels": {"doc:email:finance.ops@company.internal:msg-fin-418:c0": 2},
    },
    {
        "id": "heldout-sem-04",
        "category": "semantic",
        "query": "patching enterprise single-sign-on cryptographic token envelope flaws",
        "user_id": "employee_05",
        "group_ids": ["group_engineering", "group_security"],
        "qrels": {"doc:email:security@company.internal:msg-cve-4410:c0": 2},
    },
    {
        "id": "heldout-sem-05",
        "category": "semantic",
        "query": "increasing nearest-neighbor beam exploration depth for crowded inventory collections",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:slack:C08SRCH:thread:1700000011.000100:c0": 2},
    },
    {
        "id": "heldout-sem-06",
        "category": "semantic",
        "query": "verifying payload integrity signatures against expired timestamp boundaries",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"doc:github:company/billing-hooks:pr:308:c0": 2},
    },
    {
        "id": "heldout-sem-07",
        "category": "semantic",
        "query": "periodic master secret renewal protocol for separated tenant cryptosystems",
        "user_id": "employee_01",
        "group_ids": ["group_engineering", "group_finance", "group_security"],
        "qrels": {"doc:email:arch@company.internal:msg-rfc-0042:c0": 2},
    },
    {
        "id": "heldout-sem-08",
        "category": "semantic",
        "query": "building database indexes in the background to avoid table locking",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"doc:slack:C09DBA:thread:1700000015.000100:c0": 2},
    },
    {
        "id": "heldout-sem-09",
        "category": "semantic",
        "query": "tuning kernel network socket tracking limits to halt name resolution drops",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "qrels": {"doc:github:company/infra-runbooks:pr:89:c0": 2},
    },
    {
        "id": "heldout-sem-10",
        "category": "semantic",
        "query": "remedying erroneous billing adjustment proration remainders upon customer tier reductions",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "qrels": {"doc:email:billing@company.internal:msg-bill-312:c0": 2},
    },

    # -------------------------------------------------------------------------
    # 10 Multi-Source Cross-Silo Synthesis Scenarios (2 distinct sources)
    # -------------------------------------------------------------------------
    {
        "id": "heldout-multi-01",
        "category": "multi_source",
        "query": "What did Slack discuss regarding Kafka rebalance storms and which PR tuned session.timeout.ms?",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "required_sources": ["SLACK", "GITHUB"],
        "qrels": {
            "doc:slack:C09DBA:thread:1700000211.000100:c0": 2,
            "doc:github:company/event-workers:pr:711:c0": 2,
        },
    },
    {
        "id": "heldout-multi-02",
        "category": "multi_source",
        "query": "What email alerted SRE about NAT gateway exhaustion and what PR added AWS VPC endpoints?",
        "user_id": "employee_10",
        "group_ids": ["group_engineering"],
        "required_sources": ["EMAIL", "GITHUB"],
        "qrels": {
            "doc:email:sre@company.internal:msg-v2-112:c0": 2,
            "doc:github:company/aws-network:pr:712:c0": 2,
        },
    },
    {
        "id": "heldout-multi-03",
        "category": "multi_source",
        "query": "What did Slack find about shared RFC Message-IDs and what PR fixed email connector duplication?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "required_sources": ["SLACK", "GITHUB"],
        "qrels": {
            "doc:slack:C08SRCH:thread:1700000213.000100:c0": 2,
            "doc:github:company/email-connector:pr:713:c0": 2,
        },
    },
    {
        "id": "heldout-multi-04",
        "category": "multi_source",
        "query": "Which email flagged Stripe idempotency key truncation and which commit expanded VARCHAR length?",
        "user_id": "employee_06",
        "group_ids": ["group_engineering", "group_finance"],
        "required_sources": ["EMAIL", "GITHUB"],
        "qrels": {
            "doc:email:payments@company.internal:msg-v2-114:c0": 2,
            "doc:github:company/payment-service:commit:b119f30e2a4c:c0": 2,
        },
    },
    {
        "id": "heldout-multi-05",
        "category": "multi_source",
        "query": "What did Slack discover about insecure JWT_SECRET fallbacks and which PR aborted prod boot?",
        "user_id": "employee_05",
        "group_ids": ["group_engineering", "group_security"],
        "required_sources": ["SLACK", "GITHUB"],
        "qrels": {
            "doc:slack:C04SEC:thread:1700000215.000100:c0": 2,
            "doc:github:company/workmesh:pr:715:c0": 2,
        },
    },
    {
        "id": "heldout-multi-06",
        "category": "multi_source",
        "query": "What did Slack discuss regarding pgvector iterative_scan and what email reported the 1% recall boost?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "required_sources": ["SLACK", "EMAIL"],
        "qrels": {
            "doc:slack:C08SRCH:thread:1700000216.000100:c0": 2,
            "doc:email:search@company.internal:msg-v2-116:c0": 2,
        },
    },
    {
        "id": "heldout-multi-07",
        "category": "multi_source",
        "query": "Why did SRE request sub-50ms Prometheus histogram buckets in email and which PR exposed /metrics?",
        "user_id": "employee_04",
        "group_ids": ["group_engineering"],
        "required_sources": ["EMAIL", "GITHUB"],
        "qrels": {
            "doc:email:sre@company.internal:msg-v2-117:c0": 2,
            "doc:github:company/workmesh:pr:717:c0": 2,
        },
    },
    {
        "id": "heldout-multi-08",
        "category": "multi_source",
        "query": "What did Slack report on orphaned PostgreSQL advisory locks and which PR added TTL lease tokens?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "required_sources": ["SLACK", "GITHUB"],
        "qrels": {
            "doc:slack:C09DBA:thread:1700000218.000100:c0": 2,
            "doc:github:company/workmesh:pr:718:c0": 2,
        },
    },
    {
        "id": "heldout-multi-09",
        "category": "multi_source",
        "query": "Which email described the Okta SAML clock skew failures and what Slack update confirmed the 60s tolerance?",
        "user_id": "employee_01",
        "group_ids": ["group_engineering", "group_finance", "group_security"],
        "required_sources": ["EMAIL", "SLACK"],
        "qrels": {
            "doc:email:security@company.internal:msg-v2-119:c0": 2,
            "doc:slack:C04SEC:thread:1700000219.000100:c0": 2,
        },
    },
    {
        "id": "heldout-multi-10",
        "category": "multi_source",
        "query": "What did Slack state about non-root container user permissions and which PR baked model cache in Docker?",
        "user_id": "employee_42",
        "group_ids": ["group_engineering", "group_backend"],
        "required_sources": ["SLACK", "GITHUB"],
        "qrels": {
            "doc:slack:C06K8S:thread:1700000220.000100:c0": 2,
            "doc:github:company/workmesh:pr:720:c0": 2,
        },
    },
]


def generate_and_verify():
    # Verify semantic overlap
    import psycopg

    from app.common.config import get_settings

    s = get_settings()

    with psycopg.connect(s.database_url) as conn, conn.cursor() as cur:
        chunk_ids = []
        for q in HELDOUT_QUERIES:
            chunk_ids.extend(q["qrels"].keys())
        cur.execute("SELECT id, content FROM chunks WHERE id = ANY(%s);", (list(set(chunk_ids)),))
        chunk_map = {row[0]: row[1] for row in cur.fetchall()}

    assert len(chunk_map) == len(set(chunk_ids)), f"Missing chunks in DB! Found {len(chunk_map)} of {len(set(chunk_ids))}"

    for q in HELDOUT_QUERIES:
        if q["category"] == "semantic":
            for cid in q["qrels"].keys():
                content = chunk_map[cid]
                shared = compute_overlap(q["query"], content)
                assert len(shared) <= 1, f"Overlap failure in {q['id']}: shared={shared} (query: {q['query']})"

    HELDOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(q) for q in HELDOUT_QUERIES]
    HELDOUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Successfully generated {len(HELDOUT_QUERIES)} held-out queries at {HELDOUT_PATH}")


if __name__ == "__main__":
    generate_and_verify()
