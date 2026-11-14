# WorkMesh Multi-Step Reasoning Agent & Benchmark

This document details the architecture, security invariants, tool catalog, and empirical benchmark results for the WorkMesh autonomous multi-step reasoning agent (`POST /api/v1/agent/ask`).

---

## 1. Security Architecture & Invariants

The multi-step agent executes under strict enterprise sandbox boundaries:

1. **Per-Call Identity Binding**: The authenticated user identity (`user_id`, `role`, `groups`) is extracted exclusively from validated JWT claims and passed directly to every tool execution. Autonomous steps cannot escalate permissions or query resources outside the caller's authorization scope.
2. **Read-Only Tool Primitives**:
   - `search(query, limit)`: Runs hybrid lexical + dense vector search with pushdown ACL filtering.
   - `get_document(document_id)`: Fetches authorized chunks belonging to a specific document.
   - `get_related(chunk_id, limit)`: Traverses cross-document relationships grounded in the candidate graph.
   - `get_thread(thread_id)`: Retrieves chronologically ordered messages in an authorized Slack thread or email exchange.
   *The agent has no write tools and cannot modify database state, ACLs, or configuration.*
3. **Execution Guardrails & Budgets**:
   - `max_steps`: Hard-limited to 5 iterations (default: 5). If reached, the agent synthesizes an answer from gathered evidence.
   - `max_output_tokens`: Bounded per-step generation budget.
   - `wall_time`: Request timeout (`LLM_TIMEOUT_SECONDS`) prevents runaway execution.
4. **Durable Audit Trail**: Every tool invocation is recorded durably to PostgreSQL (`AGENT_TOOL_CALL`) with step number, tool name, SHA-256 hash of arguments (`args_hash`), returned candidate count, and caller identity.
5. **Prompt Injection Containment**:
   - Retrieved chunks are wrapped inside `<untrusted_context_data>` tags with explicit model instructions that context data cannot override system directives.
   - Citations are validated against retrieved candidates; fabricated chunk IDs are stripped.
   - If evidence is missing, the agent outputs `INSUFFICIENT_EVIDENCE`.
6. **Provider Transparency**:
   - Abstract `LlmProvider` interface with `mock` (deterministic local rule extractor, default), `gemini`, and `anthropic`.
   - `mock`: Default provider (`mock-grounded-v1`). Fully tested and validated offline; used for all CI and benchmark runs.
   - `anthropic`: Implemented, covered by mocked tests, not live-tested.
   - `gemini`: Implemented, covered by mocked tests; not live-tested in the evaluation runs (which used the deterministic `mock` provider).
   - Strict Policy: Do not claim any provider works unless it was run live.

---

## 2. Multi-Hop Evaluation Benchmark

Evaluated over 30 multi-hop queries (`data/evaluation/agent_multihop_queries.json`) requiring synthesis across multiple systems (Slack + GitHub, Email + GitHub) against the 10,000-chunk PostgreSQL + pgvector database (`python scripts/run_agent_eval.py`):

| Metric | Single-Shot (`POST /api/v1/ask`) | Multi-Step Agent (`POST /api/v1/agent/ask`) | Delta / Overhead |
|---|:---:|:---:|:---:|
| **Gold Citation Coverage** | **76.67%** | **76.67%** | **+0.00 pp** |
| **Average Steps** | 1.00 | 2.73 | +1.73 steps |
| **Mean Latency** | **194.15 ms** | **393.69 ms** | **2.03x** |
| **P50 Latency** | 188.56 ms | 402.60 ms | 2.14x |
| **P95 Latency** | 241.08 ms | 546.20 ms | 2.27x |
| **Mean Tokens Used** | **248.3 tokens** | **1,920.2 tokens** | **7.73x** |

- **Provider Used**: `mock` (`mock-grounded-v1`), recorded in [`data/evaluation/results/agent_eval_results.json`](../data/evaluation/results/agent_eval_results.json) on 2026-11-14.
- **Evaluation Dataset**: [`data/evaluation/agent_multihop_queries.json`](../data/evaluation/agent_multihop_queries.json).

### Production Recommendation
On this enterprise corpus, single-shot hybrid retrieval with query-routed RRF already surfaces the relevant multi-source candidates in step 1. The multi-step agent executes an average of 2.73 tool steps, consuming **7.73x more tokens** and **2.03x higher latency** without lifting gold citation coverage (+0.00 pp).

Single-shot `/ask` remains the recommended, latency-optimal production default for standard question answering. The agent endpoint is best reserved for complex investigative tasks where iterative discovery across distant entity relationships is necessary.
