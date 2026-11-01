"""Models for retrieval and Grounded RAG evaluation benchmark."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BenchmarkCase:
    """A representative test query with expected authoritative sources and security assertions."""

    id: str
    query: str
    query_type: str
    description: str
    expected_authoritative_sources: List[str]
    expected_keywords: List[str] = field(default_factory=list)
    authorized_user_id: str = "employee_42"
    authorized_group_ids: List[str] = field(default_factory=list)
    unauthorized_user_id: Optional[str] = None
    unauthorized_group_ids: List[str] = field(default_factory=list)


@dataclass
class BenchmarkCaseResult:
    """Evaluation result for an individual benchmark query."""

    case_id: str
    query: str
    query_type: str
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    reciprocal_rank: float
    retrieved_sources: List[str]
    citations_valid: bool
    permission_leak: bool
    latency_ms: float
    grounded: bool
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BenchmarkSummary:
    """Aggregate quality, permission isolation, and latency metrics across the benchmark suite."""

    total_queries: int
    recall_at_1: float
    recall_at_3: float
    recall_at_5: float
    mrr: float
    permission_leak_rate: float
    citation_validity_rate: float
    mean_latency_ms: float
    case_results: List[BenchmarkCaseResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_queries": self.total_queries,
            "recall_at_1": round(self.recall_at_1, 4),
            "recall_at_3": round(self.recall_at_3, 4),
            "recall_at_5": round(self.recall_at_5, 4),
            "mrr": round(self.mrr, 4),
            "permission_leak_rate": round(self.permission_leak_rate, 4),
            "citation_validity_rate": round(self.citation_validity_rate, 4),
            "mean_latency_ms": round(self.mean_latency_ms, 2),
            "case_results": [
                {
                    "case_id": cr.case_id,
                    "query": cr.query,
                    "query_type": cr.query_type,
                    "hit_at_1": cr.hit_at_1,
                    "hit_at_3": cr.hit_at_3,
                    "hit_at_5": cr.hit_at_5,
                    "reciprocal_rank": round(cr.reciprocal_rank, 4),
                    "retrieved_sources": cr.retrieved_sources,
                    "citations_valid": cr.citations_valid,
                    "permission_leak": cr.permission_leak,
                    "latency_ms": round(cr.latency_ms, 2),
                    "grounded": cr.grounded,
                }
                for cr in self.case_results
            ],
        }
