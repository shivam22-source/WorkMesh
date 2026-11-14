# WorkMesh Pushdown Access Control & Security Architecture

This document details the security architecture, SQL-level pushdown access control enforcement, authentication modes, and leak test results in WorkMesh.

---

## 1. Pushdown Access Control Architecture

Enterprise search engines commonly apply security by post-filtering results: querying the vector or lexical index first, then dropping unauthorized results in application memory. This approach introduces two critical vulnerabilities:
1. **Candidate Starvation**: If top-$k$ nearest neighbors belong to restricted documents, post-filtering discards them, returning truncated or empty result sets to low-privilege users.
2. **Side-Channel Information Leaks**: Scoring and index traversal patterns can leak existence of confidential documents.

WorkMesh implements **SQL-level pushdown access control**: permission checks are evaluated inside PostgreSQL queries using correlated semi-joins before ranking and `LIMIT` boundaries are applied.

```sql
SELECT c.id, c.document_id, c.content, c.metadata
FROM chunks c
JOIN documents d ON c.document_id = d.id
WHERE EXISTS (
    SELECT 1 FROM acl_references a
    WHERE (
        (a.resource_type = 'DOCUMENT' AND a.resource_id = c.document_id)
        OR (a.resource_type = 'CHUNK' AND a.resource_id = c.id)
    )
    AND (
        (a.principal_type = 'PUBLIC' AND a.principal_id = 'PUBLIC')
        OR (a.principal_type = 'USER' AND a.principal_id = :user_id)
        OR (a.principal_type = 'GROUP' AND a.principal_id = ANY(:user_groups))
    )
    AND a.permission = 'READ'
)
ORDER BY ... LIMIT :limit;
```

---

## 2. Authentication Modes

WorkMesh supports two runtime authentication modes controlled by `AUTH_MODE`:

### Production Mode (`AUTH_MODE=prod`, default)
- Enforces strict fail-closed JWT authentication.
- Every incoming request must supply an `Authorization: Bearer <token>` signed with `JWT_SECRET` (minimum 32 characters).
- Caller identity (`sub`), role (`role`), and authorized groups (`groups`) are extracted exclusively from cryptographically verified claims.
- Header-based identity simulation (`X-User-Id`, `X-User-Role`, `X-User-Groups`) is strictly rejected with `401 Unauthorized`.

### Development Mode (`AUTH_MODE=dev`)
- Permitted strictly for local developer testing and interactive demos.
- Allows header-based simulation (`X-User-Id`, `X-User-Role`, `X-User-Groups`).
- Emits a prominent security warning on service startup. **Dev mode is not safe for production.**

### Generating Production Tokens (`scripts/make_token.py`)

Mint signed JWT tokens using the bundled CLI utility:

**Linux / macOS (Bash):**
```bash
export JWT_SECRET="your-32-character-secret-key-minimum"
TOKEN=$(python3 scripts/make_token.py --user-id employee_42 --role ENGINEER --groups group_engineering,group_backend)

curl -s -X POST http://localhost:8000/api/v1/search \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"query": "DC-8692"}'
```

**Windows (PowerShell):**
```powershell
$env:JWT_SECRET = "your-32-character-secret-key-minimum"
$TOKEN = rag-python\.venv\Scripts\python.exe scripts\make_token.py --user-id employee_42 --role ENGINEER --groups group_engineering,group_backend

curl.exe -s -X POST http://localhost:8000/api/v1/search `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $TOKEN" `
  -d '{\"query\": \"DC-8692\"}'
```

---

## 3. Leak Test Results & Empirical Security Verification

| Evaluation Scenario | Test Invariant | Queries Evaluated | Unauthorized Leaks | Leak Rate | Verification Status |
|---|---|:---:|:---:|:---:|:---:|
| **Adversarial Security Scale Test** | Cross-tenant access isolation across 50 users and 5 departments | 500 | 0 | **0.0%** | **PASS** |
| **Denied-Identity Invariant** | Restricted identities querying confidential docs | 12 | 0 | **0.0%** | **PASS** |
| **Multi-Tenant Permission Tiers** | Low-access identities (1% corpus access) | 120 | 0 | **0.0%** | **PASS** |
| **Header Simulation Defense** | Rejection of spoofed headers in production mode | Regression suite | 0 | **0.0%** | **PASS** |

*Sources: [`data/evaluation/results/scale_benchmark_results.json`](../data/evaluation/results/scale_benchmark_results.json) and [`data/evaluation/results/ablation_v2_results.json`](../data/evaluation/results/ablation_v2_results.json).*

---

## 4. Token-Claim Staleness Trade-Off

Group memberships and roles are encoded directly inside signed JWT claims (`groups`, `role`). 

- **Benefit**: Enables stateless, low-latency pushdown SQL evaluation without querying identity providers on each search request.
- **Limitation**: Claim modifications (such as revoking user group membership) remain stale until the JWT expires (`exp`) or is refreshed. In high-security environments, shorten JWT token lifetimes (e.g. 5–15 minutes) or combine with token revocation blocklists.
