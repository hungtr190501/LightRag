"""Legal RAG Query Pipeline — Public API.

Usage:
    from legal_rag.query import legal_query, PipelineConfig, LegalQueryResult

    result = await legal_query(
        question="Quy định về chuyển nhượng đất?",
        config=PipelineConfig(top_k=20, enable_rerank=True),
        qdrant=qdrant_storage,
        rag=lightrag_instance,
    )
"""
from legal_rag.query.models import (
    AuditEntry,
    CitationValidation,
    CitationValidationResult,
    ClaimVerification,
    ClaimVerificationResult,
    ConflictItem,
    ConflictReport,
    JudgeVerdict,
    LegalQueryResult,
    PipelineConfig,
    RetrievedChunk,
    RewrittenQuery,
    VerificationResult,
)
from legal_rag.query.pipeline import legal_query

__all__ = [
    "legal_query",
    "LegalQueryResult",
    "PipelineConfig",
    "RewrittenQuery",
    "RetrievedChunk",
    "JudgeVerdict",
    "VerificationResult",
    "AuditEntry",
    # Phase 2
    "ConflictItem",
    "ConflictReport",
    "ClaimVerification",
    "ClaimVerificationResult",
    "CitationValidation",
    "CitationValidationResult",
]
