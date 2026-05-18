"""Self-Grounding Verifier — Step 13 of the pipeline (formerly Step 8).

Xác minh câu trả lời có được grounded trong context hay không.
Kiểm tra:
  1. Citation placeholders [SOURCE:xxx] → chunk thực
  2. Overall coherence check (simplified — per-claim now in claim_verifier.py)
  3. Confidence scoring (integrates ClaimVerificationResult if available)

Phase 2: Scope reduced — claim-level verification moved to claim_verifier.py.
This module focuses on citation integrity + overall coherence.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from legal_rag.citation.engine import CitationEngine
from legal_rag.llm.vllm_adapter import vllm_complete
from legal_rag.prompts import VERIFICATION_PROMPT, VERIFICATION_SYSTEM
from legal_rag.query.models import (
    AuditEntry,
    ClaimVerificationResult,
    RetrievedChunk,
    VerificationResult,
)

logger = logging.getLogger(__name__)

_citation_engine = CitationEngine()


async def verify_grounding(
    answer: str,
    chunks: list[RetrievedChunk],
    confidence_threshold: float = 0.85,
    claim_result: Optional[ClaimVerificationResult] = None,
) -> tuple[VerificationResult, AuditEntry]:
    """Verify that the answer is grounded in the retrieved context.

    Args:
        answer: Generated answer text
        chunks: Retrieved context chunks
        confidence_threshold: Minimum confidence threshold
        claim_result: Optional claim-level verification results (Phase 2)

    Returns:
        (VerificationResult, AuditEntry)
    """
    start = time.time()

    if not answer or not answer.strip():
        result = VerificationResult(
            grounded=False,
            confidence=0.0,
            unsupported_claims=["Empty answer"],
        )
        audit = AuditEntry(
            step="verification",
            status="failure",
            duration_ms=0,
            output_summary="Empty answer",
        )
        return result, audit

    # Step 1: Citation integrity check
    citation_errors = _check_citations(answer, chunks)

    # Step 2: LLM-based grounding check
    try:
        chunk_dicts = [c.to_dict() for c in chunks]
        context = _citation_engine.build_context_with_ids(chunk_dicts)

        prompt = VERIFICATION_PROMPT.format(
            answer=answer,
            context=context,
        )

        raw = await vllm_complete(
            prompt=prompt,
            system_prompt=VERIFICATION_SYSTEM,
            max_tokens=512,
            temperature=0.05,
        )

        llm_result = _parse_verification_response(raw)

        # Merge citation errors with LLM findings
        all_citation_errors = citation_errors + llm_result.citation_errors

        # Final verdict
        grounded = llm_result.grounded and len(citation_errors) == 0
        confidence = llm_result.confidence
        if citation_errors:
            confidence *= 0.8  # Penalize for citation errors

        # Phase 2: Integrate claim-level verification results
        unsupported = llm_result.unsupported_claims
        if claim_result and claim_result.total_claims > 0:
            # Blend LLM confidence with claim verification confidence
            claim_confidence = claim_result.overall_confidence
            confidence = 0.4 * confidence + 0.6 * claim_confidence
            # Add unsupported claims from claim verifier
            for claim in claim_result.claims:
                if not claim.supported:
                    unsupported.append(claim.claim_text)

        result = VerificationResult(
            grounded=grounded,
            confidence=confidence,
            unsupported_claims=unsupported,
            citation_errors=all_citation_errors,
            total_claims=llm_result.total_claims,
            supported_claims=llm_result.supported_claims,
        )

    except Exception as e:
        logger.warning("LLM verification failed: %s", e)
        # Fallback: rely only on citation check
        grounded = len(citation_errors) == 0
        result = VerificationResult(
            grounded=grounded,
            confidence=0.75 if grounded else 0.5,
            citation_errors=citation_errors,
            unsupported_claims=[],
        )

    duration_ms = (time.time() - start) * 1000
    audit = AuditEntry(
        step="verification",
        status="success",
        duration_ms=duration_ms,
        input_summary=f"Answer: {len(answer)} chars, {len(chunks)} context chunks",
        output_summary=(
            f"grounded={result.grounded}, confidence={result.confidence:.2f}, "
            f"unsupported={len(result.unsupported_claims)}, "
            f"citation_errors={len(result.citation_errors)}"
        ),
        details={
            "grounded": result.grounded,
            "confidence": result.confidence,
            "total_claims": result.total_claims,
            "supported_claims": result.supported_claims,
            "unsupported_claims": result.unsupported_claims,
            "citation_errors": result.citation_errors,
        },
    )

    logger.info(
        "Verification: grounded=%s, confidence=%.2f, unsupported=%d, citation_errors=%d",
        result.grounded,
        result.confidence,
        len(result.unsupported_claims),
        len(result.citation_errors),
    )

    return result, audit


def _check_citations(answer: str, chunks: list[RetrievedChunk]) -> list[str]:
    """Check that all [SOURCE:xxx] references map to real chunks."""
    errors = []
    chunk_ids = {c.chunk_id for c in chunks}

    # Find all SOURCE references in the answer
    source_refs = re.findall(r"\[SOURCE:([^\]]+)\]", answer)

    for ref in source_refs:
        ref = ref.strip()
        if ref not in chunk_ids:
            errors.append(f"[SOURCE:{ref}] does not match any retrieved chunk")

    return errors


def _parse_verification_response(raw: str) -> VerificationResult:
    """Parse JSON response from verification LLM."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError("No JSON found")

        return VerificationResult(
            grounded=bool(data.get("grounded", True)),
            confidence=float(data.get("confidence", 0.8)),
            unsupported_claims=data.get("unsupported_claims", []),
            citation_errors=data.get("citation_errors", []),
            total_claims=int(data.get("total_claims", 0)),
            supported_claims=int(data.get("supported_claims", 0)),
        )

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Failed to parse verification JSON: %s", e)
        return VerificationResult(
            grounded=True,
            confidence=0.75,
        )
