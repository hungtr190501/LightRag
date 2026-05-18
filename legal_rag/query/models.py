"""Data models cho Legal RAG Query Pipeline.

Tất cả dùng @dataclass để nhất quán với codebase legal_rag hiện tại.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Literal, Optional


# ── Pipeline Configuration ────────────────────────────────────────────


@dataclass
class PipelineConfig:
    """Cấu hình cho toàn bộ query pipeline."""

    # Retrieval
    top_k: int = 20
    chunk_level: Optional[str] = None  # "parent" | "child" | None (cả hai)
    use_hybrid: bool = True
    enable_lightrag: bool = True  # bật LightRAG KG retrieval
    enable_graph: bool = False     # bật Neo4j inter-document traversal
    lightrag_mode: str = "mix"     # LightRAG query mode

    # Reranker
    enable_rerank: bool = True
    rerank_top_k: int = 10
    min_rerank_score: float = -100.0  # accept any score; reranker may return negative logits

    # Judge
    enable_judge: bool = True
    max_retries: int = 2
    confidence_threshold: float = 0.85

    # Generation
    max_generation_tokens: int = 2048
    generation_temperature: float = 0.1

    # Verification
    enable_verification: bool = True

    # Dependency resolution (Step 4)
    enable_dependency_resolution: bool = True
    max_expansion_chunks: int = 15

    # Conflict detection (Step 5)
    enable_conflict_detection: bool = True

    # Claim-level verification (Step 11)
    enable_claim_verification: bool = True
    max_claims_per_batch: int = 10

    # Citation validation (Step 12)
    enable_citation_validation: bool = True

    # Graph limits (Problem 8)
    max_graph_depth: int = 2
    max_graph_neighbors: int = 10

    # Legal scoring (Step 6.5)
    enable_legal_scoring: bool = True
    legal_score_weights: dict = field(default_factory=lambda: {
        "semantic": 0.45,
        "legal_priority": 0.30,
        "authority": 0.15,
        "recency": 0.10,
    })
    exclude_expired: bool = False  # True → loại hẳn HET_HIEU_LUC / BI_THAY_THE
    min_legal_score: float = 0.0   # loại chunk có composite score thấp hơn ngưỡng này

    # Metadata filters (optional)
    doc_type: Optional[str] = None
    issuer: Optional[str] = None
    doc_numbers: Optional[list[str]] = None
    effective_after: Optional[str] = None


# ── Query Rewriter ────────────────────────────────────────────────────


@dataclass
class RewrittenQuery:
    """Kết quả từ Query Rewriter."""

    original: str
    rewritten: str
    extracted_refs: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    intent: str = ""  # "lookup" | "compare" | "explain" | "procedural"


# ── Retrieval ─────────────────────────────────────────────────────────


@dataclass
class RetrievedChunk:
    """Chunk đã retrieve từ bất kỳ nguồn nào."""

    chunk_id: str
    text: str
    score: float = 0.0

    # Source tracking
    source: str = ""  # "qdrant" | "lightrag" | "neo4j"

    # Legal metadata
    doc_number: str = ""
    doc_type: str = ""
    issuer: str = ""
    issue_date: str = ""
    effective_date: str = ""
    article: Optional[str] = None
    clause: Optional[str] = None
    point: Optional[str] = None
    page_number: int = 0
    line_start: int = 0
    line_end: int = 0
    chunk_level: str = ""  # "parent" | "child"
    parent_id: Optional[str] = None

    # Rerank score (populated after reranking)
    rerank_score: Optional[float] = None

    # Legal scoring (populated by Step 6.5)
    status: str = ""            # HIEU_LUC | HET_HIEU_LUC | BI_THAY_THE | SAP_HIEU_LUC
    is_primary_source: bool = True
    legal_score: Optional[float] = None        # composite score after Step 6.5
    legal_score_detail: Optional[dict] = None  # breakdown: semantic/priority/authority/recency

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "text": self.text,
            "score": self.score,
            "source": self.source,
            "doc_number": self.doc_number,
            "doc_type": self.doc_type,
            "issuer": self.issuer,
            "issue_date": self.issue_date,
            "effective_date": self.effective_date,
            "article": self.article,
            "clause": self.clause,
            "point": self.point,
            "page_number": self.page_number,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "chunk_level": self.chunk_level,
            "parent_id": self.parent_id,
            "rerank_score": self.rerank_score,
            "status": self.status,
            "is_primary_source": self.is_primary_source,
            "legal_score": self.legal_score,
            "legal_score_detail": self.legal_score_detail,
        }


# ── Judge ─────────────────────────────────────────────────────────────


@dataclass
class JudgeVerdict:
    """Kết quả đánh giá từ LLM Judge."""

    relevant: bool = False
    sufficient: bool = False
    confidence: float = 0.0
    missing_info: list[str] = field(default_factory=list)
    retry_required: bool = False
    retry_strategy: str = ""  # "expand_query" | "increase_topk" | "relax_filters" | "graph_traversal"
    reasoning: str = ""

    # Evidence coverage analysis (Problem 4)
    coverage_score: float = 0.0  # 0-1, how complete the evidence is
    missing_clauses: list[str] = field(default_factory=list)  # specific missing Khoản/Điểm
    missing_references: list[str] = field(default_factory=list)  # unretrieved cross-refs


# ── Verification ──────────────────────────────────────────────────────


@dataclass
class VerificationResult:
    """Kết quả xác minh grounding."""

    grounded: bool = True
    confidence: float = 1.0
    unsupported_claims: list[str] = field(default_factory=list)
    citation_errors: list[str] = field(default_factory=list)
    total_claims: int = 0
    supported_claims: int = 0


# ── Audit Trail ───────────────────────────────────────────────────────


@dataclass
class AuditEntry:
    """Một bước trong audit trail."""

    step: str
    status: Literal["success", "failure", "skipped"]
    duration_ms: float = 0.0
    input_summary: str = ""
    output_summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# ── Final Result ──────────────────────────────────────────────────────


@dataclass
class LegalQueryResult:
    """Kết quả cuối cùng từ toàn bộ pipeline."""

    # Core output
    answer: str = ""
    answer_with_citations: str = ""

    # Quality metrics
    confidence: float = 0.0
    grounded: bool = False

    # Citations
    citations: list[dict] = field(default_factory=list)

    # Retrieved context (for transparency)
    retrieved_chunks: list[dict] = field(default_factory=list)

    # Pipeline metadata
    query_original: str = ""
    query_rewritten: str = ""
    retrieval_sources: list[str] = field(default_factory=list)
    total_chunks_retrieved: int = 0
    total_chunks_after_rerank: int = 0
    judge_verdict: Optional[dict] = None
    verification: Optional[dict] = None
    retry_count: int = 0

    # Phase 2: new result fields
    conflict_report: Optional[dict] = None
    claim_verification: Optional[dict] = None
    citation_validation: Optional[dict] = None
    dependency_expansion_count: int = 0

    # Step 6.5: Legal scoring audit
    legal_score_adjust: Optional[dict] = None

    # Audit trail
    audit_trail: list[dict] = field(default_factory=list)

    # Timing
    total_duration_ms: float = 0.0

    # Status
    status: str = "success"  # "success" | "insufficient_evidence" | "error"
    error_message: str = ""

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "answer": self.answer,
            "answer_with_citations": self.answer_with_citations,
            "confidence": self.confidence,
            "grounded": self.grounded,
            "citations": self.citations,
            "retrieved_chunks": self.retrieved_chunks,
            "metadata": {
                "query_original": self.query_original,
                "query_rewritten": self.query_rewritten,
                "retrieval_sources": self.retrieval_sources,
                "total_chunks_retrieved": self.total_chunks_retrieved,
                "total_chunks_after_rerank": self.total_chunks_after_rerank,
                "judge_verdict": self.judge_verdict,
                "verification": self.verification,
                "retry_count": self.retry_count,
                "total_duration_ms": self.total_duration_ms,
                "dependency_expansion_count": self.dependency_expansion_count,
                "conflict_report": self.conflict_report,
                "claim_verification": self.claim_verification,
                "citation_validation": self.citation_validation,
                "legal_score_adjust": self.legal_score_adjust,
            },
            "audit_trail": self.audit_trail,
            "error_message": self.error_message,
        }


# ── Phase 2: Conflict Detection ──────────────────────────────────────


@dataclass
class ConflictItem:
    """Một xung đột pháp lý giữa hai chunk."""

    conflict_type: str  # "temporal" | "hierarchical" | "amendment"
    winning_chunk_id: str
    losing_chunk_id: str
    reason: str
    resolution: str  # human-readable note for generation

    def to_dict(self) -> dict:
        return {
            "conflict_type": self.conflict_type,
            "winning_chunk_id": self.winning_chunk_id,
            "losing_chunk_id": self.losing_chunk_id,
            "reason": self.reason,
            "resolution": self.resolution,
        }


@dataclass
class ConflictReport:
    """Báo cáo xung đột pháp lý tổng hợp."""

    conflicts: list[ConflictItem] = field(default_factory=list)
    resolution_notes: list[str] = field(default_factory=list)
    has_conflicts: bool = False

    def to_dict(self) -> dict:
        return {
            "has_conflicts": self.has_conflicts,
            "conflict_count": len(self.conflicts),
            "conflicts": [c.to_dict() for c in self.conflicts],
            "resolution_notes": self.resolution_notes,
        }


# ── Phase 2: Claim-Level Verification ────────────────────────────────


@dataclass
class ClaimVerification:
    """Kết quả xác minh cho một khẳng định cụ thể."""

    claim_text: str
    supported: bool
    supporting_chunk_ids: list[str] = field(default_factory=list)
    confidence: float = 0.0
    reason: str = ""


@dataclass
class ClaimVerificationResult:
    """Kết quả xác minh tổng hợp ở mức claim."""

    claims: list[ClaimVerification] = field(default_factory=list)
    total_claims: int = 0
    supported_count: int = 0
    overall_confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "total_claims": self.total_claims,
            "supported_count": self.supported_count,
            "overall_confidence": self.overall_confidence,
            "claims": [
                {
                    "claim_text": c.claim_text,
                    "supported": c.supported,
                    "supporting_chunk_ids": c.supporting_chunk_ids,
                    "confidence": c.confidence,
                    "reason": c.reason,
                }
                for c in self.claims
            ],
        }


# ── Phase 2: Citation Validation ─────────────────────────────────────


@dataclass
class CitationValidation:
    """Kết quả xác minh cho một trích dẫn cụ thể."""

    citation_text: str
    valid: bool
    chunk_id: str = ""
    exists_in_database: bool = True
    error: str = ""


@dataclass
class CitationValidationResult:
    """Kết quả xác minh citation tổng hợp."""

    validations: list[CitationValidation] = field(default_factory=list)
    valid_count: int = 0
    invalid_count: int = 0
    unverifiable_count: int = 0

    def to_dict(self) -> dict:
        return {
            "valid_count": self.valid_count,
            "invalid_count": self.invalid_count,
            "unverifiable_count": self.unverifiable_count,
            "validations": [
                {
                    "citation_text": v.citation_text,
                    "valid": v.valid,
                    "chunk_id": v.chunk_id,
                    "exists_in_database": v.exists_in_database,
                    "error": v.error,
                }
                for v in self.validations
            ],
        }
