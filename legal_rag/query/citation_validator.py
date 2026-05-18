"""Citation Existence Validation — Step 12 of the pipeline.

Validates that every legal citation in the generated answer actually exists:
  1. [SOURCE:chunk_id] placeholders → chunk_id exists in retrieved chunks
  2. Cited Điều/Khoản/Điểm → appears in the chunk's text
  3. Cited law/article not in chunks → verify it exists in Qdrant at all

Solves Problem 6: Missing Citation Validation.
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Optional

from legal_rag.query.models import (
    AuditEntry,
    CitationValidation,
    CitationValidationResult,
    RetrievedChunk,
)

if TYPE_CHECKING:
    from legal_rag.storage.qdrant_storage import QdrantLegalVectorStorage

logger = logging.getLogger(__name__)

# ── Citation Extraction Patterns ─────────────────────────────────────

# [SOURCE:chunk_id] placeholder
_SOURCE_REF_PATTERN = re.compile(r"\[SOURCE:([^\]]+)\]")

# Vietnamese legal citation patterns
_LEGAL_CITATION_PATTERN = re.compile(
    r"Điều\s+(\d+[a-z]?)"
    r"(?:\s+Khoản\s+(\d+))?"
    r"(?:\s+Điểm\s+([a-zđ]))?"
    r"(?:\s+(?:của\s+)?(?:Luật|Bộ luật|Nghị định|Thông tư|Pháp lệnh|NĐ|TT|QĐ)\s+"
    r"([^\n,;.]{3,60}(?:\s+\d{4})?))?",
    re.IGNORECASE | re.UNICODE,
)

# Broader document reference pattern
_DOC_REF_PATTERN = re.compile(
    r"(?:Luật|Bộ luật|Nghị định|Thông tư|Pháp lệnh)\s+"
    r"([^\n,;.]{3,60}(?:\s+\d{4})?)",
    re.IGNORECASE | re.UNICODE,
)


async def validate_citations(
    answer: str,
    chunks: list[RetrievedChunk],
    qdrant: Optional["QdrantLegalVectorStorage"] = None,
) -> tuple[CitationValidationResult, AuditEntry]:
    """Validate all citations in the generated answer.

    Three validation levels:
      1. SOURCE placeholder → chunk_id exists in retrieved chunks
      2. Cited article/clause → appears in the chunk text
      3. Cited law/article → exists in Qdrant database

    Args:
        answer: Generated answer text
        chunks: Retrieved context chunks
        qdrant: Qdrant storage for database existence checks

    Returns:
        (CitationValidationResult, AuditEntry)
    """
    start = time.time()

    if not answer or not answer.strip():
        result = CitationValidationResult()
        audit = AuditEntry(
            step="citation_validation",
            status="skipped",
            duration_ms=0,
            output_summary="Empty answer",
        )
        return result, audit

    validations: list[CitationValidation] = []

    # Build chunk lookup
    chunk_map = {c.chunk_id: c for c in chunks}

    # ── Level 1: Validate SOURCE placeholders ────────────────────────
    source_refs = _SOURCE_REF_PATTERN.findall(answer)
    for ref in source_refs:
        ref = ref.strip()
        if ref in chunk_map:
            validations.append(CitationValidation(
                citation_text=f"[SOURCE:{ref}]",
                valid=True,
                chunk_id=ref,
                exists_in_database=True,
            ))
        else:
            validations.append(CitationValidation(
                citation_text=f"[SOURCE:{ref}]",
                valid=False,
                chunk_id=ref,
                exists_in_database=False,
                error=f"chunk_id '{ref}' not found in retrieved chunks",
            ))

    # ── Level 2: Validate legal citations against chunk content ──────
    legal_citations = _LEGAL_CITATION_PATTERN.finditer(answer)
    for match in legal_citations:
        article = match.group(1)
        clause = match.group(2)
        point = match.group(3)
        doc_ref = match.group(4)

        citation_text = match.group(0).strip()
        article_key = f"Điều {article}"

        # Find which chunk this citation maps to
        found_in_chunk = False
        for chunk in chunks:
            if _citation_matches_chunk(article_key, clause, point, doc_ref, chunk):
                found_in_chunk = True
                # Verify the cited content actually appears in the chunk text
                if article_key.lower() in chunk.text.lower():
                    validations.append(CitationValidation(
                        citation_text=citation_text,
                        valid=True,
                        chunk_id=chunk.chunk_id,
                        exists_in_database=True,
                    ))
                else:
                    validations.append(CitationValidation(
                        citation_text=citation_text,
                        valid=False,
                        chunk_id=chunk.chunk_id,
                        exists_in_database=True,
                        error=(
                            f"'{article_key}' not found in chunk text "
                            f"(chunk from {chunk.doc_number})"
                        ),
                    ))
                break

        if not found_in_chunk and doc_ref:
            # Level 3: Check if it exists in the database at all
            exists = await _check_exists_in_database(
                article_key, doc_ref, qdrant
            )
            validations.append(CitationValidation(
                citation_text=citation_text,
                valid=False,
                exists_in_database=exists,
                error=(
                    "Citation not found in retrieved chunks"
                    + ("" if exists else " or in the database")
                ),
            ))

    # Deduplicate validations by citation_text
    seen_texts: set[str] = set()
    unique_validations: list[CitationValidation] = []
    for v in validations:
        if v.citation_text not in seen_texts:
            seen_texts.add(v.citation_text)
            unique_validations.append(v)

    # Aggregate
    valid_count = sum(1 for v in unique_validations if v.valid)
    invalid_count = sum(1 for v in unique_validations if not v.valid)
    unverifiable = sum(
        1 for v in unique_validations
        if not v.valid and not v.exists_in_database
    )

    result = CitationValidationResult(
        validations=unique_validations,
        valid_count=valid_count,
        invalid_count=invalid_count,
        unverifiable_count=unverifiable,
    )

    duration_ms = (time.time() - start) * 1000
    audit = AuditEntry(
        step="citation_validation",
        status="success",
        duration_ms=duration_ms,
        input_summary=f"Answer: {len(answer)} chars, {len(chunks)} chunks",
        output_summary=(
            f"{valid_count} valid, {invalid_count} invalid, "
            f"{unverifiable} unverifiable citations"
        ),
        details={
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "unverifiable_count": unverifiable,
            "invalid_citations": [
                v.citation_text for v in unique_validations if not v.valid
            ],
        },
    )

    logger.info(
        "Citation validation: %d valid, %d invalid, %d unverifiable in %.0fms",
        valid_count, invalid_count, unverifiable, duration_ms,
    )

    return result, audit


# ── Helpers ──────────────────────────────────────────────────────────


def _citation_matches_chunk(
    article_key: str,
    clause: Optional[str],
    point: Optional[str],
    doc_ref: Optional[str],
    chunk: RetrievedChunk,
) -> bool:
    """Check if a legal citation potentially matches a retrieved chunk."""
    # Article must match
    if chunk.article:
        chunk_art = re.search(r"Điều\s+(\d+[a-z]?)", chunk.article, re.IGNORECASE)
        ref_art = re.search(r"Điều\s+(\d+[a-z]?)", article_key, re.IGNORECASE)
        if chunk_art and ref_art and chunk_art.group(1) != ref_art.group(1):
            return False
    else:
        return False

    # If doc_ref provided, try to match against doc_number
    if doc_ref and chunk.doc_number:
        # Fuzzy match: check if doc_ref substring is in doc_number or vice versa
        doc_ref_lower = doc_ref.lower().strip()
        doc_num_lower = chunk.doc_number.lower().strip()
        if doc_ref_lower not in doc_num_lower and doc_num_lower not in doc_ref_lower:
            return False

    return True


async def _check_exists_in_database(
    article_key: str,
    doc_ref: str,
    qdrant: Optional["QdrantLegalVectorStorage"],
) -> bool:
    """Check if a legal citation exists in the Qdrant database."""
    if qdrant is None:
        return False

    try:
        results = await qdrant.get_chunks_by_article(
            doc_number=doc_ref.strip(),
            article=article_key,
            limit=1,
        )
        return len(results) > 0
    except Exception as e:
        logger.debug("Database existence check failed for %s %s: %s", article_key, doc_ref, e)
        return False
