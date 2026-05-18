"""Legal Reranker — Step 3 of the pipeline.

Wraps the existing reranker server at 192.168.2.182:8787
via LightRAG's generic_rerank_api().
"""
from __future__ import annotations

import logging
import os
import time

from legal_rag.query.models import AuditEntry, PipelineConfig, RetrievedChunk

logger = logging.getLogger(__name__)


async def rerank_chunks(
    query: str,
    chunks: list[RetrievedChunk],
    config: PipelineConfig,
) -> tuple[list[RetrievedChunk], AuditEntry]:
    """Rerank retrieved chunks using the reranker server.

    Returns:
        (reranked_chunks, audit_entry)
    """
    start = time.time()

    if not chunks:
        audit = AuditEntry(
            step="rerank",
            status="skipped",
            duration_ms=0,
            output_summary="No chunks to rerank",
        )
        return [], audit

    if not config.enable_rerank:
        audit = AuditEntry(
            step="rerank",
            status="skipped",
            duration_ms=0,
            output_summary=f"Rerank disabled, passing through {len(chunks)} chunks",
        )
        return chunks, audit

    try:
        from lightrag.rerank import generic_rerank_api

        # Truncate long texts before sending to reranker (avoid token limit errors)
        _max_chars = int(os.getenv("RERANK_MAX_CHARS", "1200"))
        documents = [c.text[:_max_chars] for c in chunks]

        # Get reranker config from env (matching .env.vllm)
        rerank_host = os.getenv(
            "RERANK_BINDING_HOST",
            "http://192.168.2.182:8787/api/v1/rerank",
        )
        rerank_model = os.getenv("RERANK_MODEL", "reranker")
        rerank_api_key = os.getenv("RERANK_BINDING_API_KEY", "not-needed")

        # Call reranker — no chunking (we pre-truncate instead)
        results = await generic_rerank_api(
            query=query,
            documents=documents,
            model=rerank_model,
            base_url=rerank_host,
            api_key=rerank_api_key,
            top_n=config.rerank_top_k,
            enable_chunking=False,
        )

        # Apply rerank scores to chunks
        reranked: list[RetrievedChunk] = []
        for result in results:
            idx = result["index"]
            score = result["relevance_score"]

            if score < config.min_rerank_score:
                continue

            if 0 <= idx < len(chunks):
                chunk = chunks[idx]
                chunk.rerank_score = score
                chunk.score = score
                reranked.append(chunk)

        # Sort by rerank score descending
        reranked.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
        reranked = reranked[: config.rerank_top_k]

        # Safety: if all scores were filtered (e.g., all below min_rerank_score),
        # fall back to top-k by original retrieval score so the pipeline never stalls
        if not reranked and results:
            logger.warning(
                "All %d rerank results filtered by min_score=%.2f; "
                "falling back to top-%d by rerank score ignoring threshold",
                len(results),
                config.min_rerank_score,
                config.rerank_top_k,
            )
            all_scored: list[RetrievedChunk] = []
            for result in results:
                idx = result["index"]
                if 0 <= idx < len(chunks):
                    chunk = chunks[idx]
                    chunk.rerank_score = result["relevance_score"]
                    chunk.score = result["relevance_score"]
                    all_scored.append(chunk)
            all_scored.sort(key=lambda c: c.rerank_score or 0.0, reverse=True)
            reranked = all_scored[: config.rerank_top_k]

        duration_ms = (time.time() - start) * 1000
        top_score = reranked[0].rerank_score if reranked else 0.0
        audit = AuditEntry(
            step="rerank",
            status="success",
            duration_ms=duration_ms,
            input_summary=f"{len(chunks)} chunks to rerank",
            output_summary=f"{len(reranked)} chunks after rerank (top_score={top_score:.3f})",
            details={
                "input_count": len(chunks),
                "output_count": len(reranked),
                "top_score": top_score,
                "bottom_score": reranked[-1].rerank_score if reranked else 0.0,
            },
        )
        logger.info(
            "Reranked %d → %d chunks in %.0fms (top_score=%.3f)",
            len(chunks),
            len(reranked),
            duration_ms,
            top_score,
        )
        return reranked, audit

    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        logger.warning(
            "Reranker failed, falling back to original order: %s", e
        )
        fallback = chunks[: config.rerank_top_k]
        audit = AuditEntry(
            step="rerank",
            status="failure",
            duration_ms=duration_ms,
            input_summary=f"{len(chunks)} chunks",
            output_summary=f"Fallback: top {len(fallback)} by original score. Error: {str(e)[:120]}",
        )
        return fallback, audit
