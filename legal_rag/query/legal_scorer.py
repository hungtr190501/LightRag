"""Legal-Aware Scoring — Step 6.5 of the query pipeline.

Composite formula:
  FinalScore = (
      SemanticScore  * w_semantic        (0.45)
    + LegalPriority  * w_legal_priority  (0.30)
    + AuthorityScore * w_authority       (0.15)
    + RecencyScore   * w_recency         (0.10)
  ) * status_demote_factor

Priorities (hard-coded, tunable via PipelineConfig.legal_score_weights):
  Hiến pháp  = 1.00
  Bộ luật    = 0.95
  Luật       = 0.90
  Pháp lệnh  = 0.85
  Nghị quyết = 0.82
  Nghị định  = 0.80
  Thông tư   = 0.70
  Quyết định = 0.60
  Công văn   = 0.40
  FAQ/Blog   = 0.10

Status demote factors:
  HIEU_LUC      → ×1.00  (no penalty)
  SAP_HIEU_LUC  → ×0.85  (coming soon, not yet effective)
  HET_HIEU_LUC  → ×0.20  (expired)
  BI_THAY_THE   → ×0.15  (replaced — strongest penalty)
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime
from typing import Optional

from legal_rag.query.models import AuditEntry, PipelineConfig, RetrievedChunk

logger = logging.getLogger(__name__)


# ── Legal Priority Table ──────────────────────────────────────────────
# Key: lowercase normalized doc_type → priority score [0, 1]

_LEGAL_PRIORITY: dict[str, float] = {
    # Constitutional
    "hiến pháp": 1.00,
    "hien phap": 1.00,
    # Bộ luật
    "bộ luật": 0.95,
    "bo luat": 0.95,
    # Luật
    "luật": 0.90,
    "luat": 0.90,
    # Pháp lệnh
    "pháp lệnh": 0.85,
    "phap lenh": 0.85,
    # Nghị quyết
    "nghị quyết": 0.82,
    "nghi quyet": 0.82,
    # Nghị định
    "nghị định": 0.80,
    "nghi dinh": 0.80,
    # Thông tư liên tịch (higher than regular thông tư)
    "thông tư liên tịch": 0.72,
    "thong tu lien tich": 0.72,
    # Thông tư
    "thông tư": 0.70,
    "thong tu": 0.70,
    # Quyết định
    "quyết định": 0.60,
    "quyet dinh": 0.60,
    # Chỉ thị
    "chỉ thị": 0.55,
    "chi thi": 0.55,
    # Công văn
    "công văn": 0.40,
    "cong van": 0.40,
    # Tờ trình / Báo cáo
    "tờ trình": 0.30,
    "to trinh": 0.30,
    "báo cáo": 0.25,
    "bao cao": 0.25,
    # Secondary sources
    "faq": 0.10,
    "blog": 0.10,
    "bình luận": 0.10,
    "binh luan": 0.10,
    "giải thích": 0.15,
    "giai thich": 0.15,
}

# Demote factor for each document status
_STATUS_DEMOTE: dict[str, float] = {
    "HIEU_LUC": 1.00,
    "SAP_HIEU_LUC": 0.85,
    "HET_HIEU_LUC": 0.20,
    "BI_THAY_THE": 0.15,
    "": 1.00,  # unknown status → no penalty
}


# ── Individual score components ───────────────────────────────────────


def compute_legal_priority(doc_type: str) -> float:
    """Map doc_type string → legal priority score [0, 1].

    Tries exact match first, then substring match.
    Falls back to 0.5 for unknown types.
    """
    if not doc_type:
        return 0.5
    key = doc_type.strip().lower()
    if key in _LEGAL_PRIORITY:
        return _LEGAL_PRIORITY[key]
    # Substring match: "Nghị định số 123" → matches "nghị định"
    for token, score in _LEGAL_PRIORITY.items():
        if token in key:
            return score
    return 0.5


def compute_recency_score(effective_date: str, issue_date: str = "") -> float:
    """Date → recency score [0, 1] using inverse-age decay.

    Score formula: 1 / (1 + age_years × 0.1)
      - 0 years  → 1.00
      - 5 years  → 0.67
      - 10 years → 0.50
      - 20 years → 0.33

    Accepts ISO dates (2023-04-17) and Vietnamese format (17/04/2023).
    """
    date_str = effective_date or issue_date
    if not date_str:
        return 0.5  # unknown date → neutral

    d: Optional[date] = None
    try:
        d = datetime.fromisoformat(date_str.split("T")[0]).date()
    except (ValueError, AttributeError):
        pass

    if d is None:
        try:
            parts = date_str.split("/")
            if len(parts) == 3:
                d = date(int(parts[2]), int(parts[1]), int(parts[0]))
        except (ValueError, IndexError):
            pass

    if d is None:
        return 0.5

    age_years = max(0.0, (date.today() - d).days / 365.25)
    return 1.0 / (1.0 + age_years * 0.1)


def compute_authority_score(
    is_primary_source: bool,
    chunk_level: str,
    status: str,
) -> float:
    """Authority score [0, 1] based on source type + chunk structure.

    Primary legal text > secondary commentary.
    Expired/replaced docs lose authority independent of legal_priority.
    """
    score = 1.0

    if not is_primary_source:
        score *= 0.3   # FAQ, blog, bình luận = strong authority penalty

    # child chunks (Khoản/Điểm) are precise but less complete than parent (Điều)
    if chunk_level == "child":
        score *= 0.92

    score *= _STATUS_DEMOTE.get(status, 1.0)

    return min(1.0, score)


def compute_final_score(
    semantic_score: float,
    doc_type: str,
    effective_date: str = "",
    issue_date: str = "",
    is_primary_source: bool = True,
    chunk_level: str = "child",
    status: str = "HIEU_LUC",
    weights: Optional[dict] = None,
) -> tuple[float, dict]:
    """Compute composite legal-aware score.

    Returns:
        (final_score [0,1], breakdown_dict)

    The status_demote_factor is applied as a final multiplier so that
    expired/replaced docs can never rank above active docs with similar
    semantic similarity — regardless of how well their text matches.
    """
    w = weights or {"semantic": 0.45, "legal_priority": 0.30, "authority": 0.15, "recency": 0.10}

    # Cross-encoder scores can be slightly outside [0,1]; clamp.
    sem = max(0.0, min(1.0, semantic_score))

    legal_prio = compute_legal_priority(doc_type)
    recency = compute_recency_score(effective_date, issue_date)
    authority = compute_authority_score(is_primary_source, chunk_level, status)

    weighted_sum = (
        sem       * w.get("semantic", 0.45)
        + legal_prio * w.get("legal_priority", 0.30)
        + authority  * w.get("authority", 0.15)
        + recency    * w.get("recency", 0.10)
    )

    # Hard multiplier: expired/replaced documents cannot escape demotion
    # even when they score high on semantic + legal_priority alone.
    status_factor = _STATUS_DEMOTE.get(status, 1.0)
    final = weighted_sum * status_factor

    breakdown = {
        "semantic": round(sem, 4),
        "semantic_w": round(sem * w.get("semantic", 0.45), 4),
        "legal_priority": round(legal_prio, 4),
        "legal_priority_w": round(legal_prio * w.get("legal_priority", 0.30), 4),
        "authority": round(authority, 4),
        "authority_w": round(authority * w.get("authority", 0.15), 4),
        "recency": round(recency, 4),
        "recency_w": round(recency * w.get("recency", 0.10), 4),
        "status_factor": status_factor,
        "final": round(final, 4),
    }

    return final, breakdown


# ── Main step function ────────────────────────────────────────────────


async def apply_legal_scoring(
    chunks: list[RetrievedChunk],
    config: PipelineConfig,
) -> tuple[list[RetrievedChunk], AuditEntry]:
    """Step 6.5: apply legal-aware composite scoring after cross-encoder rerank.

    Operations (in order):
      1. Compute composite score for every chunk
      2. Optionally exclude HET_HIEU_LUC / BI_THAY_THE entirely
      3. Filter by min_legal_score
      4. Sort by composite score descending
      5. Guarantee at least one primary legal source in top-3

    Mutates chunk.score and chunk.legal_score in-place (consistent with
    the reranker's mutation pattern in reranker.py).

    Returns:
        (scored_sorted_chunks, audit_entry)
    """
    start = time.time()

    if not chunks:
        return [], AuditEntry(
            step="legal_score_adjust",
            status="skipped",
            output_summary="No chunks to score",
        )

    if not config.enable_legal_scoring:
        return chunks, AuditEntry(
            step="legal_score_adjust",
            status="skipped",
            output_summary="Legal scoring disabled in config",
        )

    weights = config.legal_score_weights
    scored: list[RetrievedChunk] = []
    excluded_expired = 0
    excluded_low_score = 0

    for chunk in chunks:
        status = chunk.status or "HIEU_LUC"

        # Hard exclude expired/replaced when configured
        if config.exclude_expired and status in ("HET_HIEU_LUC", "BI_THAY_THE"):
            excluded_expired += 1
            continue

        # Use cross-encoder score when available, else raw retrieval score
        semantic = chunk.rerank_score if chunk.rerank_score is not None else chunk.score

        final_score, breakdown = compute_final_score(
            semantic_score=semantic,
            doc_type=chunk.doc_type,
            effective_date=chunk.effective_date,
            issue_date=chunk.issue_date,
            is_primary_source=chunk.is_primary_source,
            chunk_level=chunk.chunk_level,
            status=status,
            weights=weights,
        )

        # Filter by minimum composite score
        if final_score < config.min_legal_score:
            excluded_low_score += 1
            continue

        # Mutate in-place (consistent with reranker.py style)
        chunk.legal_score = final_score
        chunk.legal_score_detail = breakdown
        chunk.score = final_score  # overwrite so downstream sorting uses composite score
        scored.append(chunk)

    # Sort by composite score descending
    scored.sort(key=lambda c: c.legal_score or 0.0, reverse=True)

    # Guarantee at least one primary legal source appears in top-3
    # to prevent FAQ/blog chunks from dominating the generation context.
    _ensure_primary_in_top(scored, top_n=3)

    duration_ms = (time.time() - start) * 1000
    scores = [c.legal_score or 0.0 for c in scored]
    top = scored[0] if scored else None

    audit = AuditEntry(
        step="legal_score_adjust",
        status="success" if scored else "failure",
        duration_ms=duration_ms,
        input_summary=f"{len(chunks)} chunks in",
        output_summary=(
            f"{len(scored)} chunks after scoring "
            f"(excluded: {excluded_expired} expired, {excluded_low_score} low-score). "
            f"Top: {top.doc_type} {top.doc_number} score={scores[0]:.3f}"
            if top else "0 chunks out"
        ),
        details={
            "input_count": len(chunks),
            "output_count": len(scored),
            "excluded_expired": excluded_expired,
            "excluded_low_score": excluded_low_score,
            "weights": weights,
            "score_min": round(min(scores), 4) if scores else 0.0,
            "score_max": round(max(scores), 4) if scores else 0.0,
            "score_mean": round(sum(scores) / len(scores), 4) if scores else 0.0,
            "top_chunk": {
                "doc_type": top.doc_type,
                "doc_number": top.doc_number,
                "status": top.status,
                "is_primary": top.is_primary_source,
                "breakdown": top.legal_score_detail,
            } if top else None,
        },
    )

    logger.info(
        "Legal scoring: %d→%d chunks (excl_expired=%d, excl_low=%d) "
        "top=%.3f [%s %s] in %.0fms",
        len(chunks), len(scored),
        excluded_expired, excluded_low_score,
        scores[0] if scores else 0.0,
        top.doc_type if top else "?",
        top.doc_number if top else "?",
        duration_ms,
    )

    return scored, audit


# ── Helpers ───────────────────────────────────────────────────────────


def _ensure_primary_in_top(chunks: list[RetrievedChunk], top_n: int = 3) -> None:
    """Swap the highest-scoring primary source into the top-N window.

    Mutates the list in-place.  No-op if top-N already contains a primary
    source, or if no primary source exists anywhere in the list.
    """
    if len(chunks) <= top_n:
        return

    has_primary_in_top = any(c.is_primary_source for c in chunks[:top_n])
    if has_primary_in_top:
        return

    # Find the first primary source outside top-N
    for i in range(top_n, len(chunks)):
        if chunks[i].is_primary_source:
            # Insert at position top_n - 1 (last slot of top window)
            # so we don't displace the very best chunk
            chunks.insert(top_n - 1, chunks.pop(i))
            logger.debug(
                "Promoted primary source to top-%d: %s %s (score=%.3f)",
                top_n, chunks[top_n - 1].doc_type,
                chunks[top_n - 1].doc_number,
                chunks[top_n - 1].legal_score or 0.0,
            )
            return
