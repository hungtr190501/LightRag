"""Grounded Legal Generator — Step 9 of the pipeline (formerly Step 6).

Sinh câu trả lời pháp lý có grounding + citation placeholders.
CHỈ dựa trên context đã retrieve và verify.

Phase 2: Conflict-aware generation — includes conflict resolution notes
in the generation prompt so the LLM knows which provisions are superseded.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

from legal_rag.citation.engine import CitationEngine
from legal_rag.llm.vllm_adapter import vllm_complete
from legal_rag.prompts import GENERATION_PROMPT, GENERATION_SYSTEM
from legal_rag.query.models import (
    AuditEntry,
    ConflictReport,
    PipelineConfig,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)

_citation_engine = CitationEngine()


async def generate_answer(
    question: str,
    chunks: list[RetrievedChunk],
    config: PipelineConfig,
    conversation_history: list[dict] | None = None,
    conflict_report: Optional[ConflictReport] = None,
) -> tuple[str, str, list[dict], AuditEntry]:
    """Generate grounded legal answer with citations.

    Args:
        question: User's legal question
        chunks: Verified context chunks
        config: Pipeline configuration
        conversation_history: Previous conversation messages
        conflict_report: Optional conflict detection results (Phase 2)

    Returns:
        (raw_answer, answer_with_citations, citations_list, audit_entry)
    """
    start = time.time()

    if not chunks:
        audit = AuditEntry(
            step="generation",
            status="failure",
            duration_ms=0,
            output_summary="No chunks to generate from",
        )
        return "", "", [], audit

    try:
        # Build context with SOURCE IDs for citation tracking
        chunk_dicts = [c.to_dict() for c in chunks]
        context = _citation_engine.build_context_with_ids(chunk_dicts)

        # Phase 2: Append conflict resolution notes if available
        if conflict_report and conflict_report.has_conflicts:
            conflict_notes = "\n".join(conflict_report.resolution_notes)
            context += (
                f"\n\n{'='*60}\n"
                f"⚠️ THÔNG TIN XUNG ĐỘT PHÁP LÝ (BẮT BUỘC TUÂN THỦ):\n"
                f"{conflict_notes}\n"
                f"{'='*60}"
            )

        prompt = GENERATION_PROMPT.format(
            question=question,
            context=context,
        )

        # Generate answer
        raw_answer = await vllm_complete(
            prompt=prompt,
            system_prompt=GENERATION_SYSTEM,
            max_tokens=config.max_generation_tokens,
            temperature=config.generation_temperature,
        )

        # Build citations from chunks
        citations = _citation_engine.build_citations(chunk_dicts)

        # Attach reference section to answer
        answer_with_citations = _citation_engine.attach_references_section(
            raw_answer, citations
        )

        # Convert citations to dicts for serialization
        citations_list = []
        for i, c in enumerate(citations, 1):
            citations_list.append({
                "index": i,
                "doc_number": c.doc_number,
                "doc_type": c.doc_type,
                "issuer": c.issuer,
                "issue_date": c.issue_date,
                "article": c.article,
                "clause": c.clause,
                "point": c.point,
                "page_number": c.page_number,
                "line_start": c.line_start,
                "line_end": c.line_end,
                "excerpt": c.excerpt,
                "relevance_score": c.relevance_score,
                "chunk_id": c.chunk_id,
            })

        duration_ms = (time.time() - start) * 1000
        audit = AuditEntry(
            step="generation",
            status="success",
            duration_ms=duration_ms,
            input_summary=f"{len(chunks)} chunks, question: {question[:100]}",
            output_summary=f"{len(raw_answer)} chars, {len(citations_list)} citations",
            details={
                "answer_length": len(raw_answer),
                "citation_count": len(citations_list),
            },
        )

        logger.info(
            "Generated answer: %d chars, %d citations in %.0fms",
            len(raw_answer),
            len(citations_list),
            duration_ms,
        )

        return raw_answer, answer_with_citations, citations_list, audit

    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        logger.error("Generation failed: %s", e)
        audit = AuditEntry(
            step="generation",
            status="failure",
            duration_ms=duration_ms,
            output_summary=f"Generation error: {str(e)[:200]}",
        )
        return "", "", [], audit
