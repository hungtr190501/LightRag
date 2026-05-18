"""Legal RAG Query Pipeline — Full Orchestrator.

14-step pipeline (Phase 2):
  1.  Query Rewrite
  2.  Deterministic Exact Retrieval (NEW)
  3.  Hybrid Retrieval (Qdrant + LightRAG + Neo4j)
  4.  Cross-Reference Expansion (NEW)
  5.  Legal Conflict Detection (NEW)
  6.  Rerank
  7.  LLM Judge + Coverage Analysis (ENHANCED)
  8.  Retry Retrieval (if judge says insufficient, max 2 retries)
  9.  Grounded Generation (conflict-aware)
  10. Citation Attachment
  11. Claim-Level Verification (NEW)
  12. Citation Validation (NEW)
  13. Self-Grounding Verification (reduced scope)
  14. Final Answer (or rejection if confidence < threshold)
"""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import asdict
from typing import TYPE_CHECKING, Optional

from legal_rag.llm.vllm_adapter import vllm_complete
from legal_rag.prompts import (
    INSUFFICIENT_EVIDENCE_RESPONSE,
    RETRY_EXPANSION_PROMPT,
    RETRY_EXPANSION_SYSTEM,
)
from legal_rag.query.citation_validator import validate_citations
from legal_rag.query.claim_verifier import verify_claims
from legal_rag.query.conflict_resolver import detect_and_resolve_conflicts
from legal_rag.query.dependency_resolver import resolve_dependencies
from legal_rag.query.generator import generate_answer
from legal_rag.query.judge import judge_relevance
from legal_rag.query.legal_scorer import apply_legal_scoring
from legal_rag.query.models import (
    AuditEntry,
    ConflictReport,
    JudgeVerdict,
    LegalQueryResult,
    PipelineConfig,
    RetrievedChunk,
)
from legal_rag.query.query_rewriter import rewrite_query
from legal_rag.query.reranker import rerank_chunks
from legal_rag.query.retriever import exact_retrieve, hybrid_retrieve
from legal_rag.query.verifier import verify_grounding

if TYPE_CHECKING:
    from legal_rag.graph.builder import LegalGraphBuilder
    from legal_rag.storage.qdrant_storage import QdrantLegalVectorStorage
    from lightrag import LightRAG

logger = logging.getLogger(__name__)


async def legal_query(
    question: str,
    config: Optional[PipelineConfig] = None,
    qdrant: Optional["QdrantLegalVectorStorage"] = None,
    rag: Optional["LightRAG"] = None,
    graph_builder: Optional["LegalGraphBuilder"] = None,
    conversation_history: Optional[list[dict]] = None,
) -> LegalQueryResult:
    """Execute the full 14-step Legal RAG query pipeline.

    Args:
        question: User's legal question (Vietnamese)
        config: Pipeline configuration (defaults to PipelineConfig())
        qdrant: QdrantLegalVectorStorage instance
        rag: LightRAG instance
        graph_builder: LegalGraphBuilder instance (optional, for Neo4j)
        conversation_history: Previous conversation messages

    Returns:
        LegalQueryResult with answer, citations, confidence, and audit trail
    """
    pipeline_start = time.time()
    config = config or PipelineConfig()
    audit_trail: list[AuditEntry] = []
    conflict_report = ConflictReport()  # default empty

    result = LegalQueryResult(
        query_original=question,
    )

    try:
        # ══════════════════════════════════════════════════════════════
        # Step 1: Query Rewrite
        # ══════════════════════════════════════════════════════════════
        logger.info("Step 1/14: Query Rewrite")
        rewritten, audit = await rewrite_query(question, conversation_history)
        audit_trail.append(audit)
        result.query_rewritten = rewritten.rewritten

        # ══════════════════════════════════════════════════════════════
        # Step 2: Deterministic Exact Retrieval (NEW)
        # ══════════════════════════════════════════════════════════════
        logger.info("Step 2/14: Exact Retrieval")
        exact_chunks, exact_audit = await exact_retrieve(
            extracted_refs=rewritten.extracted_refs,
            keywords=rewritten.keywords,
            qdrant=qdrant,
            config=config,
        )
        audit_trail.append(exact_audit)

        # ══════════════════════════════════════════════════════════════
        # Step 3: Hybrid Retrieval
        # ══════════════════════════════════════════════════════════════
        logger.info("Step 3/14: Hybrid Retrieval")
        hybrid_chunks, hybrid_audit = await hybrid_retrieve(
            query=rewritten.rewritten,
            config=config,
            qdrant=qdrant,
            rag=rag,
            graph_builder=graph_builder,
            extracted_refs=rewritten.extracted_refs,
            keywords=rewritten.keywords,
        )
        audit_trail.append(hybrid_audit)

        # Merge exact + hybrid (exact chunks have score=1.0, highest priority)
        all_chunks = _merge_exact_and_hybrid(exact_chunks, hybrid_chunks)
        result.total_chunks_retrieved = len(all_chunks)
        result.retrieval_sources = hybrid_audit.details.get("sources_used", [])
        if exact_chunks:
            result.retrieval_sources.insert(0, "exact")

        # ══════════════════════════════════════════════════════════════
        # Step 4: Cross-Reference Expansion (NEW)
        # ══════════════════════════════════════════════════════════════
        if config.enable_dependency_resolution:
            logger.info("Step 4/14: Cross-Reference Expansion")
            all_chunks, dep_audit = await resolve_dependencies(
                chunks=all_chunks,
                qdrant=qdrant,
                config=config,
            )
            audit_trail.append(dep_audit)
            result.dependency_expansion_count = dep_audit.details.get(
                "chunks_added", 0
            )
        else:
            logger.info("Step 4/14: Dependency resolution disabled")
            audit_trail.append(AuditEntry(
                step="dependency_resolution",
                status="skipped",
                output_summary="Dependency resolution disabled in config",
            ))

        # ══════════════════════════════════════════════════════════════
        # Step 5: Legal Conflict Detection (NEW)
        # ══════════════════════════════════════════════════════════════
        if config.enable_conflict_detection:
            logger.info("Step 5/14: Legal Conflict Detection")
            all_chunks, conflict_report, conflict_audit = (
                await detect_and_resolve_conflicts(
                    question=question,
                    chunks=all_chunks,
                    config=config,
                )
            )
            audit_trail.append(conflict_audit)
            result.conflict_report = conflict_report.to_dict()
        else:
            logger.info("Step 5/14: Conflict detection disabled")
            audit_trail.append(AuditEntry(
                step="conflict_detection",
                status="skipped",
                output_summary="Conflict detection disabled in config",
            ))

        # ══════════════════════════════════════════════════════════════
        # Step 6: Rerank
        # ══════════════════════════════════════════════════════════════
        logger.info("Step 6/14: Rerank")
        reranked, rerank_audit = await rerank_chunks(
            rewritten.rewritten, all_chunks, config
        )
        audit_trail.append(rerank_audit)
        result.total_chunks_after_rerank = len(reranked)

        # ══════════════════════════════════════════════════════════════
        # Step 6.5: Legal Score Adjust (NEW)
        # ══════════════════════════════════════════════════════════════
        logger.info("Step 6.5/14: Legal Score Adjust")
        reranked, legal_score_audit = await apply_legal_scoring(reranked, config)
        audit_trail.append(legal_score_audit)
        result.legal_score_adjust = legal_score_audit.details
        result.total_chunks_after_rerank = len(reranked)  # update after possible exclusions

        # ══════════════════════════════════════════════════════════════
        # Step 7: LLM Judge + Coverage Analysis (ENHANCED)
        # ══════════════════════════════════════════════════════════════
        current_chunks = reranked
        retry_count = 0

        if config.enable_judge:
            logger.info("Step 7/14: LLM Judge + Coverage Analysis")
            verdict, judge_audit = await judge_relevance(
                question=question,
                chunks=current_chunks,
                confidence_threshold=config.confidence_threshold,
            )
            audit_trail.append(judge_audit)
            result.judge_verdict = asdict(verdict)

            # ══════════════════════════════════════════════════════════
            # Step 8: Retry Loop (if judge says insufficient)
            # ══════════════════════════════════════════════════════════
            while verdict.retry_required and retry_count < config.max_retries:
                retry_count += 1
                logger.info(
                    "Step 8/14: Retry %d/%d (strategy=%s)",
                    retry_count,
                    config.max_retries,
                    verdict.retry_strategy,
                )

                # Expand query based on retry strategy
                expanded_config, expanded_query = await _apply_retry_strategy(
                    question=question,
                    rewritten_query=rewritten.rewritten,
                    verdict=verdict,
                    config=config,
                    retry_count=retry_count,
                )

                # Re-retrieve with expanded parameters
                retry_chunks, retry_audit = await hybrid_retrieve(
                    query=expanded_query,
                    config=expanded_config,
                    qdrant=qdrant,
                    rag=rag,
                    graph_builder=graph_builder,
                    extracted_refs=rewritten.extracted_refs,
                    keywords=rewritten.keywords,
                )
                retry_audit.step = f"retry_retrieval_{retry_count}"
                audit_trail.append(retry_audit)

                # Merge new chunks with existing (keep unique)
                merged = _merge_retry_chunks(current_chunks, retry_chunks)

                # Re-rerank merged set
                merged_reranked, rr_audit = await rerank_chunks(
                    expanded_query, merged, config
                )
                rr_audit.step = f"retry_rerank_{retry_count}"
                audit_trail.append(rr_audit)
                current_chunks = merged_reranked

                # Re-judge
                verdict, jd_audit = await judge_relevance(
                    question=question,
                    chunks=current_chunks,
                    confidence_threshold=config.confidence_threshold,
                )
                jd_audit.step = f"retry_judge_{retry_count}"
                audit_trail.append(jd_audit)
                result.judge_verdict = asdict(verdict)

            result.retry_count = retry_count
        else:
            logger.info("Step 7-8/14: Judge disabled, skipping")
            audit_trail.append(AuditEntry(
                step="judge",
                status="skipped",
                output_summary="Judge disabled in config",
            ))

        # Check if we have enough confidence to proceed
        final_confidence = (
            result.judge_verdict.get("confidence", 1.0)
            if result.judge_verdict else 1.0
        )

        if not current_chunks:
            # No chunks at all → insufficient evidence
            logger.warning("No chunks available after retrieval + retry")
            result.status = "insufficient_evidence"
            result.answer = INSUFFICIENT_EVIDENCE_RESPONSE.format(
                reasons="- Không tìm được tài liệu pháp lý liên quan trong cơ sở dữ liệu",
                confidence=0.0,
            )
            result.answer_with_citations = result.answer
            result.confidence = 0.0
            result.grounded = False
            result.audit_trail = [asdict(a) for a in audit_trail]
            result.total_duration_ms = (time.time() - pipeline_start) * 1000
            return result

        if final_confidence < config.confidence_threshold and config.enable_judge:
            # Judge says insufficient even after retries
            missing = (
                result.judge_verdict.get("missing_info", [])
                if result.judge_verdict else []
            )
            reasons = (
                "\n".join(f"- {m}" for m in missing) if missing
                else "- Tài liệu được tìm thấy không đủ liên quan hoặc đầy đủ"
            )
            logger.warning(
                "Confidence %.2f < threshold %.2f after %d retries",
                final_confidence,
                config.confidence_threshold,
                retry_count,
            )
            result.status = "insufficient_evidence"
            result.answer = INSUFFICIENT_EVIDENCE_RESPONSE.format(
                reasons=reasons,
                confidence=final_confidence,
            )
            result.answer_with_citations = result.answer
            result.confidence = final_confidence
            result.grounded = False
            result.retrieved_chunks = [c.to_dict() for c in current_chunks[:5]]
            result.audit_trail = [asdict(a) for a in audit_trail]
            result.total_duration_ms = (time.time() - pipeline_start) * 1000
            return result

        # ══════════════════════════════════════════════════════════════
        # Step 9 + 10: Grounded Generation + Citation Attachment
        # ══════════════════════════════════════════════════════════════
        logger.info("Step 9-10/14: Generation + Citations")
        raw_answer, answer_with_citations, citations, gen_audit = (
            await generate_answer(
                question=question,
                chunks=current_chunks,
                config=config,
                conversation_history=conversation_history,
                conflict_report=conflict_report,
            )
        )
        audit_trail.append(gen_audit)

        if not raw_answer:
            result.status = "error"
            result.error_message = "Generation returned empty answer"
            result.audit_trail = [asdict(a) for a in audit_trail]
            result.total_duration_ms = (time.time() - pipeline_start) * 1000
            return result

        result.answer = raw_answer
        result.answer_with_citations = answer_with_citations
        result.citations = citations
        result.retrieved_chunks = [c.to_dict() for c in current_chunks]

        # ══════════════════════════════════════════════════════════════
        # Step 11: Claim-Level Verification (NEW)
        # ══════════════════════════════════════════════════════════════
        claim_result = None
        if config.enable_claim_verification:
            logger.info("Step 11/14: Claim-Level Verification")
            claim_result, claim_audit = await verify_claims(
                answer=raw_answer,
                chunks=current_chunks,
                config=config,
            )
            audit_trail.append(claim_audit)
            result.claim_verification = claim_result.to_dict()
        else:
            logger.info("Step 11/14: Claim verification disabled")
            audit_trail.append(AuditEntry(
                step="claim_verification",
                status="skipped",
                output_summary="Claim verification disabled in config",
            ))

        # ══════════════════════════════════════════════════════════════
        # Step 12: Citation Validation (NEW)
        # ══════════════════════════════════════════════════════════════
        if config.enable_citation_validation:
            logger.info("Step 12/14: Citation Validation")
            cit_result, cit_audit = await validate_citations(
                answer=raw_answer,
                chunks=current_chunks,
                qdrant=qdrant,
            )
            audit_trail.append(cit_audit)
            result.citation_validation = cit_result.to_dict()
        else:
            logger.info("Step 12/14: Citation validation disabled")
            audit_trail.append(AuditEntry(
                step="citation_validation",
                status="skipped",
                output_summary="Citation validation disabled in config",
            ))

        # ══════════════════════════════════════════════════════════════
        # Step 13: Self-Grounding Verification
        # ══════════════════════════════════════════════════════════════
        if config.enable_verification:
            logger.info("Step 13/14: Self-Grounding Verification")
            verification, ver_audit = await verify_grounding(
                answer=raw_answer,
                chunks=current_chunks,
                confidence_threshold=config.confidence_threshold,
                claim_result=claim_result,
            )
            audit_trail.append(ver_audit)
            result.verification = asdict(verification)
            result.confidence = verification.confidence
            result.grounded = verification.grounded

            # If verification fails → reject answer
            if (
                not verification.grounded
                or verification.confidence < config.confidence_threshold
            ):
                logger.warning(
                    "Verification failed: grounded=%s, confidence=%.2f",
                    verification.grounded,
                    verification.confidence,
                )
                unsupported = verification.unsupported_claims
                reasons = (
                    "\n".join(f"- {c}" for c in unsupported) if unsupported
                    else "- Một số khẳng định trong câu trả lời không được hỗ trợ bởi tài liệu gốc"
                )
                result.status = "insufficient_evidence"
                # Keep the answer but add warning header
                result.answer_with_citations = (
                    "⚠️ **Cảnh báo**: Một số thông tin trong câu trả lời "
                    "có thể chưa được xác minh đầy đủ.\n\n"
                    + answer_with_citations
                    + f"\n\n*Độ tin cậy: {verification.confidence:.0%}*"
                )
        else:
            logger.info("Step 13/14: Verification disabled")
            result.confidence = final_confidence
            result.grounded = True
            audit_trail.append(AuditEntry(
                step="verification",
                status="skipped",
                output_summary="Verification disabled in config",
            ))

        # ══════════════════════════════════════════════════════════════
        # Step 14: Final Answer
        # ══════════════════════════════════════════════════════════════
        logger.info("Step 14/14: Final Answer")
        if result.status != "insufficient_evidence":
            result.status = "success"

        result.audit_trail = [asdict(a) for a in audit_trail]
        result.total_duration_ms = (time.time() - pipeline_start) * 1000

        logger.info(
            "Pipeline complete: status=%s, confidence=%.2f, "
            "duration=%.0fms, retries=%d, conflicts=%d, deps=%d",
            result.status,
            result.confidence,
            result.total_duration_ms,
            result.retry_count,
            len(conflict_report.conflicts),
            result.dependency_expansion_count,
        )

        return result

    except Exception as e:
        logger.error("Pipeline error: %s", e, exc_info=True)
        result.status = "error"
        result.error_message = str(e)
        result.audit_trail = [asdict(a) for a in audit_trail]
        result.total_duration_ms = (time.time() - pipeline_start) * 1000
        return result


# ── Retry Strategy ────────────────────────────────────────────────────


async def _apply_retry_strategy(
    question: str,
    rewritten_query: str,
    verdict: JudgeVerdict,
    config: PipelineConfig,
    retry_count: int,
) -> tuple[PipelineConfig, str]:
    """Apply retry strategy based on judge verdict.

    Returns:
        (modified_config, expanded_query)
    """
    from dataclasses import replace

    strategy = verdict.retry_strategy
    expanded_query = rewritten_query

    # Create modified config based on strategy
    if strategy == "increase_topk":
        modified = replace(config, top_k=config.top_k * 2)
    elif strategy == "relax_filters":
        modified = replace(
            config,
            doc_type=None,
            issuer=None,
            effective_after=None,
            top_k=config.top_k + 10,
        )
    elif strategy == "graph_traversal":
        modified = replace(config, enable_graph=True, top_k=config.top_k + 5)
    else:
        # Default: expand_query
        modified = replace(config, top_k=config.top_k + 10)

    # For expand_query strategy: use LLM to generate expanded query
    if strategy in ("expand_query", ""):
        try:
            expansion_prompt = RETRY_EXPANSION_PROMPT.format(
                question=question,
                rewritten_query=rewritten_query,
                failure_reason=verdict.reasoning,
                missing_info="\n".join(f"- {m}" for m in verdict.missing_info),
            )
            raw = await vllm_complete(
                prompt=expansion_prompt,
                system_prompt=RETRY_EXPANSION_SYSTEM,
                max_tokens=256,
                temperature=0.1,
            )
            expanded = _parse_expansion(raw)
            if expanded:
                expanded_query = expanded
        except Exception as e:
            logger.warning("Query expansion failed: %s", e)

    logger.info(
        "Retry strategy=%s: top_k=%d→%d, query=%s",
        strategy,
        config.top_k,
        modified.top_k,
        expanded_query[:80],
    )

    return modified, expanded_query


def _parse_expansion(raw: str) -> str:
    """Parse expanded query from LLM response."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            data = json.loads(json_match.group())
            return data.get("expanded_query", "")
    except (json.JSONDecodeError, ValueError):
        pass

    return ""


def _merge_retry_chunks(
    existing: list[RetrievedChunk],
    new_chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Merge new chunks with existing, keeping unique by chunk_id."""
    seen_ids = {c.chunk_id for c in existing}
    merged = list(existing)
    for chunk in new_chunks:
        if chunk.chunk_id not in seen_ids:
            seen_ids.add(chunk.chunk_id)
            merged.append(chunk)
    return merged


def _merge_exact_and_hybrid(
    exact: list[RetrievedChunk],
    hybrid: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """Merge exact retrieval results with hybrid results.

    Exact chunks (score=1.0) get priority. Duplicates from hybrid are dropped.
    """
    if not exact:
        return hybrid
    if not hybrid:
        return exact

    seen_ids = {c.chunk_id for c in exact}
    merged = list(exact)
    for chunk in hybrid:
        if chunk.chunk_id not in seen_ids:
            seen_ids.add(chunk.chunk_id)
            merged.append(chunk)

    # Sort: exact first (score=1.0), then by score descending
    merged.sort(key=lambda c: c.score, reverse=True)
    return merged
