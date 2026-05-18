"""Legal Conflict Detection & Resolution — Step 5 of the pipeline.

Detects and resolves conflicts between retrieved legal provisions:
  Layer A: Temporal conflicts (newer law supersedes older)
  Layer B: Hierarchical conflicts (Luật > Nghị định > Thông tư)
  Layer C: Amendment/replacement detection (LLM-assisted)

Solves Problems 2 + 3: Missing Legal Conflict Detection + Missing Legal Reasoning.
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict
from dataclasses import asdict
from typing import Optional

from legal_rag.llm.vllm_adapter import vllm_complete
from legal_rag.query.models import (
    AuditEntry,
    ConflictItem,
    ConflictReport,
    PipelineConfig,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)

# ── Legal Document Hierarchy ─────────────────────────────────────────
# Higher rank = higher authority. When two provisions conflict,
# the one from the higher-ranked doc_type wins.

_HIERARCHY_RANK: dict[str, int] = {
    "Hiến pháp": 100,
    "Luật": 90,
    "Bộ luật": 90,
    "Pháp lệnh": 80,
    "Nghị quyết": 75,
    "Nghị định": 70,
    "Quyết định": 65,
    "Thông tư": 60,
    "Thông tư liên tịch": 60,
    "Chỉ thị": 50,
    "Công văn": 40,
}


def _get_hierarchy_rank(doc_type: str) -> int:
    """Get hierarchy rank for a document type. Unknown types get rank 30."""
    if not doc_type:
        return 30
    # Try exact match first
    if doc_type in _HIERARCHY_RANK:
        return _HIERARCHY_RANK[doc_type]
    # Try partial match (e.g., "Nghị định" in "Nghị định của Chính phủ")
    for key, rank in _HIERARCHY_RANK.items():
        if key in doc_type:
            return rank
    return 30


# ── Conflict Detection Prompt ────────────────────────────────────────

_CONFLICT_SYSTEM = """\
Bạn là chuyên gia phân tích xung đột pháp lý Việt Nam.
Nhiệm vụ: xác định xem hai điều khoản pháp lý có xung đột không.

Bạn PHẢI trả về JSON thuần túy, KHÔNG giải thích thêm."""

_CONFLICT_PROMPT = """\
HAI ĐIỀU KHOẢN PHÁP LÝ CẦN SO SÁNH:

ĐIỀU KHOẢN A (từ {doc_a}):
{text_a}

ĐIỀU KHOẢN B (từ {doc_b}):
{text_b}

Phân tích:
1. Hai điều khoản có quy định về cùng một vấn đề không?
2. Nếu cùng vấn đề, nội dung có mâu thuẫn không?
3. Nếu mâu thuẫn, điều khoản nào nên được ưu tiên và tại sao?

Trả về JSON:
{{
  "same_topic": true/false,
  "conflicts": true/false,
  "winner": "A" hoặc "B" hoặc "",
  "reason": "giải thích ngắn gọn",
  "resolution": "hướng giải quyết xung đột"
}}

CHỈ trả về JSON thuần túy."""


async def detect_and_resolve_conflicts(
    question: str,
    chunks: list[RetrievedChunk],
    config: PipelineConfig,
) -> tuple[list[RetrievedChunk], ConflictReport, AuditEntry]:
    """Detect and resolve legal conflicts among retrieved chunks.

    Three-layer detection:
      A) Temporal: newer effective_date supersedes older
      B) Hierarchical: Luật > Nghị định > Thông tư
      C) Amendment: LLM-assisted detection for ambiguous pairs

    Args:
        question: Original user question
        chunks: Retrieved chunks to analyze
        config: Pipeline configuration

    Returns:
        (annotated_chunks, conflict_report, audit_entry)
    """
    start = time.time()

    if len(chunks) < 2:
        report = ConflictReport()
        audit = AuditEntry(
            step="conflict_detection",
            status="skipped",
            duration_ms=(time.time() - start) * 1000,
            output_summary="Less than 2 chunks — no conflicts possible",
        )
        return chunks, report, audit

    all_conflicts: list[ConflictItem] = []
    resolution_notes: list[str] = []

    # ── Layer A: Temporal Conflicts ──────────────────────────────────
    temporal_conflicts, temporal_notes = _detect_temporal_conflicts(chunks)
    all_conflicts.extend(temporal_conflicts)
    resolution_notes.extend(temporal_notes)

    # ── Layer B: Hierarchical Conflicts ──────────────────────────────
    hierarchy_conflicts, hierarchy_notes = _detect_hierarchical_conflicts(chunks)
    all_conflicts.extend(hierarchy_conflicts)
    resolution_notes.extend(hierarchy_notes)

    # ── Layer C: LLM-Assisted Amendment Detection ────────────────────
    # Only run for pairs flagged by Layer A/B to avoid unnecessary LLM calls
    if all_conflicts:
        try:
            amendment_conflicts, amendment_notes = await _detect_amendments_llm(
                chunks, all_conflicts,
            )
            all_conflicts.extend(amendment_conflicts)
            resolution_notes.extend(amendment_notes)
        except Exception as e:
            logger.warning("LLM amendment detection failed: %s", e)

    # Annotate chunks with conflict info
    annotated = _annotate_chunks_with_conflicts(chunks, all_conflicts)

    report = ConflictReport(
        conflicts=all_conflicts,
        resolution_notes=resolution_notes,
        has_conflicts=len(all_conflicts) > 0,
    )

    duration_ms = (time.time() - start) * 1000
    audit = AuditEntry(
        step="conflict_detection",
        status="success",
        duration_ms=duration_ms,
        input_summary=f"{len(chunks)} chunks analyzed",
        output_summary=(
            f"{len(all_conflicts)} conflicts detected "
            f"(temporal={len(temporal_conflicts)}, "
            f"hierarchy={len(hierarchy_conflicts)})"
        ),
        details={
            "total_conflicts": len(all_conflicts),
            "temporal_conflicts": len(temporal_conflicts),
            "hierarchy_conflicts": len(hierarchy_conflicts),
            "resolution_notes": resolution_notes,
        },
    )

    logger.info(
        "Conflict detection: %d conflicts in %d chunks (%.0fms)",
        len(all_conflicts), len(chunks), duration_ms,
    )

    return annotated, report, audit


# ── Layer A: Temporal Conflict Detection ─────────────────────────────


def _detect_temporal_conflicts(
    chunks: list[RetrievedChunk],
) -> tuple[list[ConflictItem], list[str]]:
    """Detect temporal conflicts — newer law supersedes older on same topic.

    Groups chunks by article pattern across different documents.
    If same article exists in multiple docs, the newer one wins.
    """
    conflicts: list[ConflictItem] = []
    notes: list[str] = []

    # Group chunks by (article, topic similarity) across different documents
    article_groups: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for chunk in chunks:
        if chunk.article:
            # Normalize article for grouping
            art_key = _normalize_article_key(chunk.article)
            if art_key:
                article_groups[art_key].append(chunk)

    for art_key, group in article_groups.items():
        # Only check if same article appears in multiple documents
        doc_chunks: dict[str, list[RetrievedChunk]] = defaultdict(list)
        for chunk in group:
            if chunk.doc_number:
                doc_chunks[chunk.doc_number].append(chunk)

        if len(doc_chunks) < 2:
            continue

        # Find newest and oldest by effective_date or issue_date
        doc_dates: list[tuple[str, str, list[RetrievedChunk]]] = []
        for doc_num, doc_group in doc_chunks.items():
            date = (
                doc_group[0].effective_date
                or doc_group[0].issue_date
                or ""
            )
            doc_dates.append((doc_num, date, doc_group))

        # Sort by date descending (newest first)
        doc_dates.sort(key=lambda x: x[1], reverse=True)

        if len(doc_dates) >= 2:
            newest_doc, newest_date, newest_chunks = doc_dates[0]
            for older_doc, older_date, older_chunks in doc_dates[1:]:
                if not newest_date or not older_date:
                    continue
                if newest_date > older_date:
                    # Temporal conflict detected
                    for new_c in newest_chunks:
                        for old_c in older_chunks:
                            conflicts.append(ConflictItem(
                                conflict_type="temporal",
                                winning_chunk_id=new_c.chunk_id,
                                losing_chunk_id=old_c.chunk_id,
                                reason=(
                                    f"{art_key}: {newest_doc} ({newest_date}) "
                                    f"thay thế {older_doc} ({older_date})"
                                ),
                                resolution=(
                                    f"Sử dụng quy định từ {newest_doc} "
                                    f"(có hiệu lực {newest_date}) thay vì "
                                    f"{older_doc} ({older_date})"
                                ),
                            ))
                    notes.append(
                        f"⚠️ XUNG ĐỘT THỜI GIAN: {art_key} — "
                        f"{newest_doc} ({newest_date}) thay thế "
                        f"{older_doc} ({older_date}). "
                        f"CHỈ sử dụng phiên bản mới hơn."
                    )

    return conflicts, notes


# ── Layer B: Hierarchical Conflict Detection ─────────────────────────


def _detect_hierarchical_conflicts(
    chunks: list[RetrievedChunk],
) -> tuple[list[ConflictItem], list[str]]:
    """Detect hierarchical conflicts — higher-ranked doc_type wins.

    Legal hierarchy: Hiến pháp > Luật > Pháp lệnh > Nghị định > Thông tư > QĐ
    """
    conflicts: list[ConflictItem] = []
    notes: list[str] = []

    # Group chunks by article key
    article_groups: dict[str, list[RetrievedChunk]] = defaultdict(list)
    for chunk in chunks:
        if chunk.article:
            art_key = _normalize_article_key(chunk.article)
            if art_key:
                article_groups[art_key].append(chunk)

    for art_key, group in article_groups.items():
        if len(group) < 2:
            continue

        # Check if different doc_types have different hierarchy ranks
        ranked_chunks: list[tuple[int, RetrievedChunk]] = []
        for chunk in group:
            rank = _get_hierarchy_rank(chunk.doc_type)
            ranked_chunks.append((rank, chunk))

        # Sort by rank descending (highest authority first)
        ranked_chunks.sort(key=lambda x: x[0], reverse=True)

        # Find conflicts between different ranks
        highest_rank = ranked_chunks[0][0]
        for rank, chunk in ranked_chunks[1:]:
            if rank < highest_rank and chunk.doc_number != ranked_chunks[0][1].doc_number:
                top_chunk = ranked_chunks[0][1]
                conflicts.append(ConflictItem(
                    conflict_type="hierarchical",
                    winning_chunk_id=top_chunk.chunk_id,
                    losing_chunk_id=chunk.chunk_id,
                    reason=(
                        f"{art_key}: {top_chunk.doc_type} ({top_chunk.doc_number}) "
                        f"có hiệu lực cao hơn {chunk.doc_type} ({chunk.doc_number})"
                    ),
                    resolution=(
                        f"Ưu tiên quy định từ {top_chunk.doc_type} "
                        f"({top_chunk.doc_number}) vì có thứ bậc pháp lý cao hơn "
                        f"{chunk.doc_type} ({chunk.doc_number})"
                    ),
                ))
                notes.append(
                    f"⚠️ XUNG ĐỘT THỨ BẬC: {art_key} — "
                    f"{top_chunk.doc_type} ({top_chunk.doc_number}) "
                    f"có hiệu lực cao hơn {chunk.doc_type} ({chunk.doc_number}). "
                    f"Ưu tiên văn bản có thứ bậc cao hơn."
                )

    return conflicts, notes


# ── Layer C: LLM-Assisted Amendment Detection ───────────────────────


async def _detect_amendments_llm(
    chunks: list[RetrievedChunk],
    existing_conflicts: list[ConflictItem],
) -> tuple[list[ConflictItem], list[str]]:
    """Use LLM to verify and refine conflicts found by Layers A/B.

    Only analyzes chunk pairs that were already flagged as potential conflicts
    to minimize LLM calls.
    """
    conflicts: list[ConflictItem] = []
    notes: list[str] = []

    # Build chunk lookup
    chunk_map = {c.chunk_id: c for c in chunks}

    # Analyze up to 5 conflict pairs with LLM
    analyzed_pairs: set[tuple[str, str]] = set()

    for conflict in existing_conflicts[:5]:
        pair_key = (conflict.winning_chunk_id, conflict.losing_chunk_id)
        if pair_key in analyzed_pairs:
            continue
        analyzed_pairs.add(pair_key)

        winner = chunk_map.get(conflict.winning_chunk_id)
        loser = chunk_map.get(conflict.losing_chunk_id)
        if not winner or not loser:
            continue

        try:
            prompt = _CONFLICT_PROMPT.format(
                doc_a=f"{winner.doc_type} {winner.doc_number}",
                text_a=winner.text[:800],
                doc_b=f"{loser.doc_type} {loser.doc_number}",
                text_b=loser.text[:800],
            )

            raw = await vllm_complete(
                prompt=prompt,
                system_prompt=_CONFLICT_SYSTEM,
                max_tokens=256,
                temperature=0.05,
            )

            result = _parse_conflict_response(raw)
            if result and result.get("conflicts"):
                llm_winner = result.get("winner", "")
                resolution = result.get("resolution", "")

                if llm_winner == "B":
                    # LLM disagrees with our deterministic analysis
                    conflicts.append(ConflictItem(
                        conflict_type="amendment",
                        winning_chunk_id=loser.chunk_id,
                        losing_chunk_id=winner.chunk_id,
                        reason=result.get("reason", "LLM analysis"),
                        resolution=resolution,
                    ))
                    notes.append(
                        f"⚠️ SỬA ĐỔI: LLM xác nhận {loser.doc_number} "
                        f"ưu tiên hơn {winner.doc_number}. "
                        f"Lý do: {resolution}"
                    )
        except Exception as e:
            logger.warning("LLM conflict analysis failed: %s", e)

    return conflicts, notes


# ── Chunk Annotation ─────────────────────────────────────────────────


def _annotate_chunks_with_conflicts(
    chunks: list[RetrievedChunk],
    conflicts: list[ConflictItem],
) -> list[RetrievedChunk]:
    """Add conflict annotations to chunk texts for generation awareness.

    Losing chunks get a warning prefix so the generator knows to deprioritize.
    """
    if not conflicts:
        return chunks

    losing_ids: dict[str, str] = {}  # chunk_id → resolution note
    for conflict in conflicts:
        losing_ids[conflict.losing_chunk_id] = conflict.resolution

    annotated = []
    for chunk in chunks:
        if chunk.chunk_id in losing_ids:
            # Add warning to the chunk text
            note = losing_ids[chunk.chunk_id]
            annotated_text = (
                f"[⚠️ LƯU Ý: Quy định này có thể đã được thay thế hoặc "
                f"có văn bản ưu tiên hơn. {note}]\n\n{chunk.text}"
            )
            # Create a copy with annotated text
            annotated.append(RetrievedChunk(
                chunk_id=chunk.chunk_id,
                text=annotated_text,
                score=chunk.score * 0.7,  # penalize score
                source=chunk.source,
                doc_number=chunk.doc_number,
                doc_type=chunk.doc_type,
                issuer=chunk.issuer,
                issue_date=chunk.issue_date,
                effective_date=chunk.effective_date,
                article=chunk.article,
                clause=chunk.clause,
                point=chunk.point,
                page_number=chunk.page_number,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                chunk_level=chunk.chunk_level,
                parent_id=chunk.parent_id,
                rerank_score=chunk.rerank_score,
            ))
        else:
            annotated.append(chunk)

    return annotated


# ── Helpers ──────────────────────────────────────────────────────────


def _normalize_article_key(article: str) -> str:
    """Normalize 'Điều 18' → 'Điều 18' for grouping."""
    match = re.search(r"Điều\s+(\d+[a-z]?)", article, re.IGNORECASE)
    return f"Điều {match.group(1)}" if match else ""


def _parse_conflict_response(raw: str) -> Optional[dict]:
    """Parse JSON from LLM conflict analysis response."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            return json.loads(json_match.group())
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse conflict JSON: %s", e)

    return None
