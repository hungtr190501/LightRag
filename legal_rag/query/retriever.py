"""Multi-Source Hybrid Retriever — Steps 2-3 of the pipeline.

Orchestrate retrieval from multiple sources:
  1. Deterministic exact retrieval (payload filter, no semantic search)
  2. Qdrant: hybrid dense+sparse search with metadata filtering
  3. LightRAG: KG-based entity/relation/chunk retrieval
  4. Neo4j: inter-document graph traversal

Merge + deduplicate kết quả từ tất cả nguồn.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from typing import TYPE_CHECKING, Optional

from legal_rag.query.models import AuditEntry, PipelineConfig, RetrievedChunk

if TYPE_CHECKING:
    from legal_rag.graph.builder import LegalGraphBuilder
    from legal_rag.storage.qdrant_storage import QdrantLegalVectorStorage
    from lightrag import LightRAG

logger = logging.getLogger(__name__)


# ── Exact Retrieval (Step 2 — deterministic) ─────────────────────────

# Patterns to parse structured references from query rewriter output
_REF_ARTICLE_PATTERN = re.compile(
    r"Điều\s+(\d+[a-z]?)", re.IGNORECASE | re.UNICODE
)
_REF_DOC_PATTERN = re.compile(
    r"(?:Luật|Nghị định|Thông tư|Bộ luật|Pháp lệnh|NĐ|TT|QĐ)\s+"
    r"[^\n,;]{3,60}(?:\s+\d{4})?",
    re.IGNORECASE | re.UNICODE,
)
_REF_DOC_NUMBER_PATTERN = re.compile(
    r"\d{1,3}/\d{4}/(?:NĐ|TT|QĐ|CT|NQ|PL|NQLT)-[A-ZĐ]+",
    re.IGNORECASE | re.UNICODE,
)


async def exact_retrieve(
    extracted_refs: list[str],
    keywords: list[str],
    qdrant: Optional["QdrantLegalVectorStorage"] = None,
    config: Optional[PipelineConfig] = None,
) -> tuple[list[RetrievedChunk], AuditEntry]:
    """Deterministic exact retrieval using payload filters only.

    Parses extracted references (e.g., "Điều 18 Luật Đất đai 2024") into
    structured filters and queries Qdrant by exact payload match — NO
    semantic search involved. Results get score=1.0 (highest priority).

    Returns:
        (exact_chunks, audit_entry)
    """
    start = time.time()

    if not extracted_refs or qdrant is None:
        audit = AuditEntry(
            step="exact_retrieval",
            status="skipped",
            duration_ms=(time.time() - start) * 1000,
            output_summary="No refs or no Qdrant available",
        )
        return [], audit

    all_chunks: list[RetrievedChunk] = []
    lookup_details: list[dict] = []

    for ref in extracted_refs:
        # Extract article number(s) from the reference
        articles = _REF_ARTICLE_PATTERN.findall(ref)
        # Extract doc number (e.g., "10/2024/NĐ-CP") or doc name (e.g., "Luật Đất đai 2024")
        doc_numbers = _REF_DOC_NUMBER_PATTERN.findall(ref)
        doc_names = _REF_DOC_PATTERN.findall(ref)

        # Determine doc identifier for filter
        doc_filter = doc_numbers[0] if doc_numbers else (doc_names[0].strip() if doc_names else "")

        if not articles or not doc_filter:
            # Cannot parse into structured filter — skip
            lookup_details.append({
                "ref": ref, "status": "unparseable",
                "articles": articles, "doc_filter": doc_filter,
            })
            continue

        for article_num in articles:
            article_key = f"Điều {article_num}"
            try:
                results = await qdrant.get_chunks_by_article(
                    doc_number=doc_filter,
                    article=article_key,
                    limit=5,
                )
                for r in results:
                    all_chunks.append(RetrievedChunk(
                        chunk_id=r.get("chunk_id", r.get("id", "")),
                        text=r.get("text", r.get("content", "")),
                        score=1.0,  # highest priority for exact match
                        source="exact",
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
                        status=r.get("status", "HIEU_LUC"),
                        is_primary_source=r.get("is_primary_source", True),
                    ))
                lookup_details.append({
                    "ref": ref, "article": article_key,
                    "doc_filter": doc_filter, "found": len(results),
                })
            except Exception as e:
                logger.warning("Exact lookup failed for %s %s: %s", article_key, doc_filter, e)
                lookup_details.append({
                    "ref": ref, "article": article_key,
                    "doc_filter": doc_filter, "error": str(e),
                })

    # Deduplicate
    merged = _deduplicate_chunks(all_chunks)

    duration_ms = (time.time() - start) * 1000
    audit = AuditEntry(
        step="exact_retrieval",
        status="success" if merged else "skipped",
        duration_ms=duration_ms,
        input_summary=f"{len(extracted_refs)} refs: {extracted_refs[:3]}",
        output_summary=f"{len(merged)} exact chunks found",
        details={
            "lookups": lookup_details,
            "total_found": len(merged),
        },
    )

    logger.info(
        "Exact retrieval: %d chunks from %d refs in %.0fms",
        len(merged), len(extracted_refs), duration_ms,
    )

    return merged, audit


async def hybrid_retrieve(
    query: str,
    config: PipelineConfig,
    qdrant: Optional["QdrantLegalVectorStorage"] = None,
    rag: Optional["LightRAG"] = None,
    graph_builder: Optional["LegalGraphBuilder"] = None,
    extracted_refs: Optional[list[str]] = None,
    keywords: Optional[list[str]] = None,
) -> tuple[list[RetrievedChunk], AuditEntry]:
    """Run multi-source retrieval and merge results.

    Returns:
        (merged_chunks, audit_entry)
    """
    start = time.time()
    all_chunks: list[RetrievedChunk] = []
    sources_used: list[str] = []
    details: dict = {}

    # Launch independent retrievals in parallel
    tasks = []

    if qdrant is not None:
        tasks.append(("qdrant", _retrieve_qdrant(query, config, qdrant)))

    if config.enable_lightrag and rag is not None:
        tasks.append(("lightrag", _retrieve_lightrag(query, config, rag)))

    if config.enable_graph and graph_builder is not None and extracted_refs:
        tasks.append(("neo4j", _retrieve_graph(extracted_refs, graph_builder, config)))

    if not tasks:
        logger.warning("No retrieval sources available")
        audit = AuditEntry(
            step="retrieval",
            status="failure",
            duration_ms=(time.time() - start) * 1000,
            output_summary="No retrieval sources configured",
        )
        return [], audit

    # Run all retrievals in parallel
    results = await asyncio.gather(
        *[t[1] for t in tasks],
        return_exceptions=True,
    )

    for (source_name, _), result in zip(tasks, results):
        if isinstance(result, Exception):
            err_msg = f"{type(result).__name__}: {result}"
            logger.error("Retrieval from %s failed: %s", source_name, err_msg)
            details[f"{source_name}_error"] = err_msg
            continue

        chunks = result
        sources_used.append(source_name)
        details[f"{source_name}_count"] = len(chunks)
        all_chunks.extend(chunks)

    # Deduplicate by chunk_id (keep highest score)
    merged = _deduplicate_chunks(all_chunks)

    # Sort by score descending
    merged.sort(key=lambda c: c.score, reverse=True)

    duration_ms = (time.time() - start) * 1000
    errors = {k: v for k, v in details.items() if k.endswith("_error")}
    error_summary = "; ".join(f"{k}={v[:80]}" for k, v in errors.items()) if errors else ""
    summary = f"{len(merged)} chunks from {sources_used}"
    if error_summary:
        summary += f" | ERRORS: {error_summary}"
    audit = AuditEntry(
        step="retrieval",
        status="success" if merged else "failure",
        duration_ms=duration_ms,
        input_summary=query[:200],
        output_summary=summary,
        details={
            "sources_used": sources_used,
            "total_before_dedup": len(all_chunks),
            "total_after_dedup": len(merged),
            **details,
        },
    )

    logger.info(
        "Retrieved %d chunks (deduped from %d) from %s in %.0fms",
        len(merged),
        len(all_chunks),
        sources_used,
        duration_ms,
    )

    return merged, audit


# ── Qdrant retrieval ──────────────────────────────────────────────────


async def _retrieve_qdrant(
    query: str,
    config: PipelineConfig,
    qdrant: "QdrantLegalVectorStorage",
) -> list[RetrievedChunk]:
    """Hybrid search in Qdrant with metadata filtering."""
    results = await qdrant.query_legal(
        query=query,
        top_k=config.top_k,
        doc_type=config.doc_type,
        issuer=config.issuer,
        doc_numbers=config.doc_numbers,
        effective_after=config.effective_after,
        chunk_level=config.chunk_level,
        use_hybrid=config.use_hybrid,
    )

    chunks = []
    for r in results:
        chunks.append(RetrievedChunk(
            chunk_id=r.get("chunk_id", r.get("id", "")),
            text=r.get("text", r.get("content", "")),
            score=r.get("score", 0.0),
            source="qdrant",
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
            status=r.get("status", "HIEU_LUC"),
            is_primary_source=r.get("is_primary_source", True),
        ))
    return chunks


# ── LightRAG retrieval ────────────────────────────────────────────────


async def _retrieve_lightrag(
    query: str,
    config: PipelineConfig,
    rag: "LightRAG",
) -> list[RetrievedChunk]:
    """KG-based retrieval via LightRAG aquery_data."""
    from lightrag.base import QueryParam

    param = QueryParam(
        mode=config.lightrag_mode,
        top_k=config.top_k,
        only_need_context=True,
    )

    result = await rag.aquery_data(query, param)

    chunks = []
    data = result.get("data", {})

    # Extract chunks from LightRAG response
    for chunk_data in data.get("chunks", []):
        chunk_id = chunk_data.get("chunk_id", "")
        if not chunk_id:
            # Generate deterministic ID from content
            content = chunk_data.get("content", "")
            chunk_id = hashlib.sha256(content[:200].encode()).hexdigest()[:24]

        chunks.append(RetrievedChunk(
            chunk_id=chunk_id,
            text=chunk_data.get("content", ""),
            score=0.5,  # LightRAG doesn't return score for chunks
            source="lightrag",
        ))

    # Also include entity descriptions as context
    for entity in data.get("entities", []):
        entity_name = entity.get("entity_name", "")
        description = entity.get("description", "")
        if description:
            eid = hashlib.sha256(
                f"entity_{entity_name}".encode()
            ).hexdigest()[:24]
            chunks.append(RetrievedChunk(
                chunk_id=eid,
                text=f"[{entity.get('entity_type', 'ENTITY')}] {entity_name}: {description}",
                score=0.4,
                source="lightrag",
            ))

    # Include relationship descriptions
    for rel in data.get("relationships", []):
        description = rel.get("description", "")
        if description:
            rid = hashlib.sha256(
                f"rel_{rel.get('src_id', '')}_{rel.get('tgt_id', '')}".encode()
            ).hexdigest()[:24]
            chunks.append(RetrievedChunk(
                chunk_id=rid,
                text=f"[RELATION] {rel.get('src_id', '')} → {rel.get('tgt_id', '')}: {description}",
                score=0.35,
                source="lightrag",
            ))

    return chunks


# ── Neo4j graph traversal ────────────────────────────────────────────


async def _retrieve_graph(
    extracted_refs: list[str],
    graph_builder: "LegalGraphBuilder",
    config: Optional[PipelineConfig] = None,
) -> list[RetrievedChunk]:
    """Find related documents via Neo4j graph traversal.

    Uses extracted legal references (doc numbers) from the query
    to find connected documents. Respects graph traversal limits
    from config (Problem 8: Potential Graph Explosion).
    """
    chunks = []
    max_refs = 5  # Limit to first 5 refs
    max_neighbors = 10 if config is None else config.max_graph_neighbors
    max_depth = 2 if config is None else config.max_graph_depth

    for ref in extracted_refs[:max_refs]:
        try:
            related = await graph_builder.get_related_documents(
                doc_number=ref,
                max_depth=max_depth,
                max_neighbors=max_neighbors,
                status_filter="HIEU_LUC",
            )
            for doc in related:
                rid = hashlib.sha256(
                    f"graph_{doc.get('doc_number', '')}_{doc.get('relation_type', '')}".encode()
                ).hexdigest()[:24]
                text_parts = [
                    f"[VĂN BẢN LIÊN QUAN] {doc.get('doc_type', '')} số {doc.get('doc_number', '')}",
                    f"Tên: {doc.get('title', '')}",
                    f"Quan hệ với {ref}: {doc.get('relation_type', '')}",
                    f"Trạng thái: {doc.get('status', '')}",
                ]
                chunks.append(RetrievedChunk(
                    chunk_id=rid,
                    text="\n".join(t for t in text_parts if t),
                    score=0.3,
                    source="neo4j",
                    doc_number=doc.get("doc_number", ""),
                    doc_type=doc.get("doc_type", ""),
                ))
        except Exception as e:
            logger.warning("Graph traversal failed for ref '%s': %s", ref, e)

    return chunks


# ── Deduplication ─────────────────────────────────────────────────────


def _deduplicate_chunks(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """Deduplicate chunks by chunk_id, keeping highest score.

    Also deduplicates by text similarity (first 200 chars) to handle
    same content from different sources with different IDs.
    """
    seen_ids: dict[str, RetrievedChunk] = {}
    seen_texts: dict[str, RetrievedChunk] = {}

    for chunk in chunks:
        # Deduplicate by ID
        if chunk.chunk_id in seen_ids:
            existing = seen_ids[chunk.chunk_id]
            if chunk.score > existing.score:
                seen_ids[chunk.chunk_id] = chunk
            continue

        # Deduplicate by text fingerprint
        text_key = chunk.text[:200].strip().lower()
        if text_key in seen_texts:
            existing = seen_texts[text_key]
            if chunk.score > existing.score:
                # Replace in both dicts
                old_id = existing.chunk_id
                seen_ids.pop(old_id, None)
                seen_ids[chunk.chunk_id] = chunk
                seen_texts[text_key] = chunk
            continue

        seen_ids[chunk.chunk_id] = chunk
        seen_texts[text_key] = chunk

    return list(seen_ids.values())
