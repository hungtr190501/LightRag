"""Cross-Reference Dependency Resolver — Step 4 of the pipeline.

Scans retrieved chunks for intra-document cross-references (e.g., "theo Điều 21")
and automatically retrieves the referenced articles from Qdrant.

This solves Problem 1: when Điều 20 says "theo quy định tại Điều 21 đến Điều 29a",
the system must auto-retrieve those referenced articles to provide complete context.
"""
from __future__ import annotations

import logging
import re
import time
from typing import TYPE_CHECKING, Optional

from legal_rag.query.models import AuditEntry, PipelineConfig, RetrievedChunk

if TYPE_CHECKING:
    from legal_rag.storage.qdrant_storage import QdrantLegalVectorStorage

logger = logging.getLogger(__name__)

# ── Cross-Reference Patterns ─────────────────────────────────────────

# Match "theo/tại/căn cứ Điều X" — same-document reference
_SINGLE_ARTICLE_REF = re.compile(
    r"(?:theo|tại|căn cứ|quy định tại|nêu tại|nói tại|theo quy định tại)"
    r"\s+(?:Điều\s+(\d+[a-z]?))",
    re.IGNORECASE | re.UNICODE,
)

# Match "Khoản X Điều Y" — clause-level reference
_CLAUSE_ARTICLE_REF = re.compile(
    r"Khoản\s+\d+\s+Điều\s+(\d+[a-z]?)",
    re.IGNORECASE | re.UNICODE,
)

# Match "Điểm x Khoản y Điều z" — point-level reference
_POINT_CLAUSE_ARTICLE_REF = re.compile(
    r"Điểm\s+[a-zđ]\s+Khoản\s+\d+\s+Điều\s+(\d+[a-z]?)",
    re.IGNORECASE | re.UNICODE,
)

# Match "từ Điều X đến Điều Y" — article range
_ARTICLE_RANGE_REF = re.compile(
    r"(?:từ\s+)?Điều\s+(\d+[a-z]?)\s+đến\s+Điều\s+(\d+[a-z]?)",
    re.IGNORECASE | re.UNICODE,
)

# Match "các Điều X, Y, Z" — article list
_ARTICLE_LIST_REF = re.compile(
    r"(?:các\s+)?Điều\s+(\d+[a-z]?)(?:\s*,\s*(\d+[a-z]?))+",
    re.IGNORECASE | re.UNICODE,
)

# Direct "Điều X" mentions (broad catch-all, lower priority)
_DIRECT_ARTICLE_REF = re.compile(
    r"Điều\s+(\d+[a-z]?)",
    re.IGNORECASE | re.UNICODE,
)


async def resolve_dependencies(
    chunks: list[RetrievedChunk],
    qdrant: Optional["QdrantLegalVectorStorage"],
    config: PipelineConfig,
) -> tuple[list[RetrievedChunk], AuditEntry]:
    """Scan chunks for cross-references and auto-retrieve referenced articles.

    Args:
        chunks: Already-retrieved chunks to scan for cross-refs
        qdrant: Qdrant storage for exact article lookup
        config: Pipeline config (uses max_expansion_chunks)

    Returns:
        (expanded_chunks, audit_entry) — original chunks + newly resolved deps
    """
    start = time.time()

    if not chunks or qdrant is None:
        audit = AuditEntry(
            step="dependency_resolution",
            status="skipped",
            duration_ms=(time.time() - start) * 1000,
            output_summary="No chunks or no Qdrant available",
        )
        return chunks, audit

    # Collect all cross-references from all chunks
    existing_articles: dict[str, set[str]] = {}  # doc_number → set of article nums
    for chunk in chunks:
        if chunk.doc_number and chunk.article:
            existing_articles.setdefault(chunk.doc_number, set()).add(
                _normalize_article(chunk.article)
            )

    # Extract cross-references from chunk texts
    refs_to_fetch: list[tuple[str, str]] = []  # (doc_number, article_key)
    ref_sources: dict[str, list[str]] = {}  # article_key → list of source chunk_ids

    for chunk in chunks:
        if not chunk.doc_number:
            continue

        referenced_articles = _extract_cross_references(chunk.text)
        doc_articles = existing_articles.get(chunk.doc_number, set())

        for article_num in referenced_articles:
            # Skip if we already have this article
            if article_num in doc_articles:
                continue

            article_key = f"Điều {article_num}"
            fetch_pair = (chunk.doc_number, article_key)

            if fetch_pair not in refs_to_fetch:
                refs_to_fetch.append(fetch_pair)
                ref_sources[article_key] = []

            ref_sources.setdefault(article_key, []).append(chunk.chunk_id)

    if not refs_to_fetch:
        duration_ms = (time.time() - start) * 1000
        audit = AuditEntry(
            step="dependency_resolution",
            status="success",
            duration_ms=duration_ms,
            output_summary="No cross-references to resolve",
            details={"refs_found": 0, "chunks_added": 0},
        )
        return chunks, audit

    # Cap the number of lookups to avoid runaway expansion
    max_lookups = config.max_expansion_chunks
    refs_to_fetch = refs_to_fetch[:max_lookups]

    # Fetch referenced articles from Qdrant
    new_chunks: list[RetrievedChunk] = []
    lookup_results: list[dict] = []

    for doc_number, article_key in refs_to_fetch:
        try:
            results = await qdrant.get_chunks_by_article(
                doc_number=doc_number,
                article=article_key,
                limit=3,  # max 3 chunks per referenced article
            )
            for r in results:
                new_chunks.append(RetrievedChunk(
                    chunk_id=r.get("chunk_id", r.get("id", "")),
                    text=r.get("text", r.get("content", "")),
                    score=0.9,  # high but below exact (1.0)
                    source="dependency",
                    doc_number=r.get("doc_number", ""),
                    doc_type=r.get("doc_type", ""),
                    issuer=r.get("issuer", ""),
                    issue_date=r.get("issue_date", ""),
                    effective_date=r.get("effective_date", ""),
                    article=r.get("article"),
                    clause=r.get("clause"),
                    point=r.get("point"),
                    page_number=r.get("page_number", 0),
                    line_start=r.get("line_start", 0),
                    line_end=r.get("line_end", 0),
                    chunk_level=r.get("chunk_level", ""),
                    parent_id=r.get("parent_id"),
                ))
            lookup_results.append({
                "doc_number": doc_number,
                "article": article_key,
                "found": len(results),
                "referenced_by": ref_sources.get(article_key, [])[:3],
            })
        except Exception as e:
            logger.warning(
                "Dependency lookup failed for %s %s: %s",
                doc_number, article_key, e,
            )
            lookup_results.append({
                "doc_number": doc_number,
                "article": article_key,
                "error": str(e),
            })

    # Deduplicate new chunks against existing
    existing_ids = {c.chunk_id for c in chunks}
    unique_new = [c for c in new_chunks if c.chunk_id not in existing_ids]

    # Cap total expansion
    unique_new = unique_new[:config.max_expansion_chunks]

    # Merge
    expanded = list(chunks) + unique_new

    duration_ms = (time.time() - start) * 1000
    audit = AuditEntry(
        step="dependency_resolution",
        status="success",
        duration_ms=duration_ms,
        input_summary=f"{len(chunks)} chunks scanned, {len(refs_to_fetch)} refs found",
        output_summary=f"{len(unique_new)} new chunks added via dependency resolution",
        details={
            "refs_found": len(refs_to_fetch),
            "chunks_added": len(unique_new),
            "lookups": lookup_results,
        },
    )

    logger.info(
        "Dependency resolution: %d refs → %d new chunks in %.0fms",
        len(refs_to_fetch), len(unique_new), duration_ms,
    )

    return expanded, audit


# ── Reference Extraction ─────────────────────────────────────────────


def _extract_cross_references(text: str) -> set[str]:
    """Extract all referenced article numbers from a chunk's text.

    Returns set of normalized article numbers (e.g., {"21", "22", "29a"}).
    """
    refs: set[str] = set()

    # Article ranges: "từ Điều 21 đến Điều 29a"
    for match in _ARTICLE_RANGE_REF.finditer(text):
        start_art = match.group(1)
        end_art = match.group(2)
        # Try to expand numeric range
        expanded = _expand_article_range(start_art, end_art)
        refs.update(expanded)

    # Single article references: "theo Điều 21", "căn cứ Điều 15"
    for match in _SINGLE_ARTICLE_REF.finditer(text):
        refs.add(match.group(1))

    # Clause-level: "Khoản 2 Điều 18"
    for match in _CLAUSE_ARTICLE_REF.finditer(text):
        refs.add(match.group(1))

    # Point-level: "Điểm a Khoản 1 Điều 20"
    for match in _POINT_CLAUSE_ARTICLE_REF.finditer(text):
        refs.add(match.group(1))

    return refs


def _expand_article_range(start: str, end: str) -> list[str]:
    """Expand "Điều 21 đến Điều 29a" into [21, 22, ..., 29, 29a].

    Handles simple numeric ranges and ignores suffix letters for range.
    """
    try:
        # Extract numeric parts
        start_num = int(re.match(r"(\d+)", start).group(1))
        end_match = re.match(r"(\d+)([a-z]?)", end)
        end_num = int(end_match.group(1))
        end_suffix = end_match.group(2)

        if end_num < start_num or (end_num - start_num) > 50:
            # Invalid or too large range — just return endpoints
            return [start, end]

        result = [str(n) for n in range(start_num, end_num + 1)]

        # If end has a suffix (e.g., "29a"), include it
        if end_suffix:
            result.append(f"{end_num}{end_suffix}")

        return result

    except (AttributeError, ValueError):
        return [start, end]


def _normalize_article(article: str) -> str:
    """Normalize 'Điều 18' → '18', 'điều 18' → '18'."""
    match = re.search(r"(\d+[a-z]?)", article)
    return match.group(1) if match else article
