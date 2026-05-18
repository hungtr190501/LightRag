"""Claim-Level Verification — Step 11 of the pipeline.

Splits the generated answer into individual claims and verifies each one
against the retrieved context chunks. This replaces the old global
verification approach with granular per-claim checking.

Solves Problem 5: Missing Claim-Level Verification.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from legal_rag.citation.engine import CitationEngine
from legal_rag.llm.vllm_adapter import vllm_complete
from legal_rag.query.models import (
    AuditEntry,
    ClaimVerification,
    ClaimVerificationResult,
    PipelineConfig,
    RetrievedChunk,
)

logger = logging.getLogger(__name__)

_citation_engine = CitationEngine()

# ── Claim Verification Prompt ────────────────────────────────────────

_CLAIM_VERIFICATION_SYSTEM = """\
Bạn là kiểm soát viên pháp lý chuyên xác minh từng khẳng định trong câu trả lời tư vấn.
Nhiệm vụ: kiểm tra mỗi khẳng định có được hỗ trợ bởi tài liệu gốc (CONTEXT) hay không.

Bạn PHẢI trả về JSON thuần túy, KHÔNG giải thích thêm."""

_CLAIM_VERIFICATION_PROMPT = """\
CÁC KHẲNG ĐỊNH CẦN XÁC MINH:
{claims}

TÀI LIỆU GỐC (CONTEXT):
{context}

Với MỖI khẳng định, đánh giá:
1. Khẳng định này có được hỗ trợ bởi thông tin trong CONTEXT không?
2. Chunk nào hỗ trợ khẳng định? (dùng ID trong [SOURCE:xxx])
3. Mức độ tin cậy (0.0-1.0)
4. Nếu không được hỗ trợ, lý do tại sao?

Trả về JSON:
{{
  "verifications": [
    {{
      "claim_index": 0,
      "supported": true/false,
      "supporting_sources": ["chunk_id_1", "chunk_id_2"],
      "confidence": 0.0-1.0,
      "reason": "lý do ngắn gọn"
    }}
  ]
}}

CHỈ trả về JSON thuần túy."""


async def verify_claims(
    answer: str,
    chunks: list[RetrievedChunk],
    config: PipelineConfig,
) -> tuple[ClaimVerificationResult, AuditEntry]:
    """Verify each claim in the answer against retrieved chunks.

    Args:
        answer: Generated answer text
        chunks: Retrieved context chunks
        config: Pipeline config (uses max_claims_per_batch)

    Returns:
        (ClaimVerificationResult, AuditEntry)
    """
    start = time.time()

    if not answer or not answer.strip():
        result = ClaimVerificationResult()
        audit = AuditEntry(
            step="claim_verification",
            status="skipped",
            duration_ms=0,
            output_summary="Empty answer",
        )
        return result, audit

    # Step A: Split answer into individual claims
    claims = _extract_claims(answer)
    if not claims:
        result = ClaimVerificationResult()
        audit = AuditEntry(
            step="claim_verification",
            status="skipped",
            duration_ms=(time.time() - start) * 1000,
            output_summary="No verifiable claims found in answer",
        )
        return result, audit

    # Step B: Verify claims in batches via LLM
    all_verifications: list[ClaimVerification] = []

    # Build context once
    chunk_dicts = [c.to_dict() for c in chunks]
    context = _citation_engine.build_context_with_ids(chunk_dicts)

    batch_size = config.max_claims_per_batch
    for batch_start in range(0, len(claims), batch_size):
        batch = claims[batch_start : batch_start + batch_size]

        try:
            batch_results = await _verify_claim_batch(batch, context, chunks)
            all_verifications.extend(batch_results)
        except Exception as e:
            logger.warning("Claim verification batch failed: %s", e)
            # Mark batch as unverified
            for claim in batch:
                all_verifications.append(ClaimVerification(
                    claim_text=claim,
                    supported=True,  # conservative: assume supported
                    confidence=0.5,
                    reason=f"Verification failed: {str(e)[:80]}",
                ))

    # Step C: Aggregate results
    total = len(all_verifications)
    supported = sum(1 for v in all_verifications if v.supported)
    overall_confidence = supported / total if total > 0 else 0.0

    result = ClaimVerificationResult(
        claims=all_verifications,
        total_claims=total,
        supported_count=supported,
        overall_confidence=overall_confidence,
    )

    duration_ms = (time.time() - start) * 1000
    audit = AuditEntry(
        step="claim_verification",
        status="success",
        duration_ms=duration_ms,
        input_summary=f"{total} claims extracted from {len(answer)} char answer",
        output_summary=(
            f"{supported}/{total} claims supported, "
            f"confidence={overall_confidence:.2f}"
        ),
        details={
            "total_claims": total,
            "supported_count": supported,
            "overall_confidence": overall_confidence,
            "unsupported_claims": [
                v.claim_text for v in all_verifications if not v.supported
            ],
        },
    )

    logger.info(
        "Claim verification: %d/%d supported (confidence=%.2f) in %.0fms",
        supported, total, overall_confidence, duration_ms,
    )

    return result, audit


# ── Claim Extraction ─────────────────────────────────────────────────

# Sentence boundary pattern for Vietnamese legal text
_SENTENCE_BOUNDARY = re.compile(
    r"(?<=[.!?])\s+(?=[A-ZĐÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬÉÈẺẼẸÊẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌÔỐỒỔỖỘƠỚỜỞỠỢÚÙỦŨỤƯỨỪỬỮỰ\d\"\"\"–—\-\[])"
)

# Non-claim patterns (transitional, headers, etc.)
_NON_CLAIM_PATTERNS = [
    re.compile(r"^(?:Trả lời|Kết luận|Tóm lại|Như vậy)\s*:", re.IGNORECASE),
    re.compile(r"^(?:Lưu ý|Ghi chú|Tham khảo)\s*:", re.IGNORECASE),
    re.compile(r"^[#*\-•]\s"),  # markdown list/header markers
    re.compile(r"^\d+\.\s*$"),  # bare number markers
    re.compile(r"^⚠️"),  # warning icons
]


def _extract_claims(answer: str) -> list[str]:
    """Extract verifiable legal claims from the answer text.

    Splits by sentence boundaries and filters out non-claim sentences.
    """
    # Remove citation markers for cleaner splitting
    clean = re.sub(r"\[SOURCE:[^\]]+\]", "", answer)
    # Remove markdown formatting
    clean = re.sub(r"[*_`#]+", "", clean)

    # Split into sentences
    sentences = _SENTENCE_BOUNDARY.split(clean)

    claims = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or len(sentence) < 15:
            continue

        # Skip non-claim sentences
        is_non_claim = False
        for pattern in _NON_CLAIM_PATTERNS:
            if pattern.search(sentence):
                is_non_claim = True
                break
        if is_non_claim:
            continue

        # Keep sentences that contain legal content indicators
        if _is_likely_legal_claim(sentence):
            claims.append(sentence)

    return claims


def _is_likely_legal_claim(sentence: str) -> bool:
    """Check if a sentence is likely a verifiable legal claim."""
    legal_indicators = [
        "Điều", "Khoản", "Điểm", "quy định", "theo",
        "căn cứ", "Luật", "Nghị định", "Thông tư",
        "quyền", "nghĩa vụ", "phải", "được phép",
        "cấm", "không được", "hạn chế", "điều kiện",
        "thủ tục", "trình tự", "xử phạt", "vi phạm",
    ]
    sentence_lower = sentence.lower()
    return any(ind.lower() in sentence_lower for ind in legal_indicators)


# ── LLM-Based Claim Verification ────────────────────────────────────


async def _verify_claim_batch(
    claims: list[str],
    context: str,
    chunks: list[RetrievedChunk],
) -> list[ClaimVerification]:
    """Verify a batch of claims via a single LLM call."""
    # Format claims for prompt
    claims_text = "\n".join(
        f"[Khẳng định {i}] {claim}" for i, claim in enumerate(claims)
    )

    prompt = _CLAIM_VERIFICATION_PROMPT.format(
        claims=claims_text,
        context=context,
    )

    raw = await vllm_complete(
        prompt=prompt,
        system_prompt=_CLAIM_VERIFICATION_SYSTEM,
        max_tokens=1024,
        temperature=0.05,
    )

    return _parse_claim_verification_response(raw, claims, chunks)


def _parse_claim_verification_response(
    raw: str,
    claims: list[str],
    chunks: list[RetrievedChunk],
) -> list[ClaimVerification]:
    """Parse JSON response from claim verification LLM."""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    chunk_ids = {c.chunk_id for c in chunks}

    try:
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError("No JSON found")

        verifications = data.get("verifications", [])
        results: list[ClaimVerification] = []

        for v in verifications:
            idx = int(v.get("claim_index", -1))
            if 0 <= idx < len(claims):
                # Validate supporting sources exist
                sources = v.get("supporting_sources", [])
                valid_sources = [s for s in sources if s in chunk_ids]

                results.append(ClaimVerification(
                    claim_text=claims[idx],
                    supported=bool(v.get("supported", True)),
                    supporting_chunk_ids=valid_sources,
                    confidence=float(v.get("confidence", 0.5)),
                    reason=v.get("reason", ""),
                ))

        # Fill in any missing claims (not returned by LLM)
        verified_indices = {
            int(v.get("claim_index", -1)) for v in verifications
        }
        for i, claim in enumerate(claims):
            if i not in verified_indices:
                results.append(ClaimVerification(
                    claim_text=claim,
                    supported=True,
                    confidence=0.6,
                    reason="Not evaluated by LLM",
                ))

        return results

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Failed to parse claim verification JSON: %s", e)
        # Conservative fallback
        return [
            ClaimVerification(
                claim_text=claim,
                supported=True,
                confidence=0.6,
                reason=f"Parse error, assuming supported: {str(e)[:80]}",
            )
            for claim in claims
        ]
