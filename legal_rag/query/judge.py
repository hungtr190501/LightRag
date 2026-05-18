"""LLM Relevance Judge — Step 7 of the pipeline (formerly Step 4).

Đánh giá chất lượng tài liệu retrieved trước khi sinh câu trả lời.
Quyết định: đủ tốt để generate, hay cần retry retrieval.

Phase 2 enhancement: Evidence Coverage Analysis (Problem 4)
  - Clause coverage: checks missing Khoản/Điểm within each Điều
  - Exception coverage: checks for unretrieved exception clauses
  - Reference coverage: checks if cross-referenced articles are present
"""
from __future__ import annotations

import json
import logging
import re
import time
from collections import defaultdict

from legal_rag.llm.vllm_adapter import vllm_complete
from legal_rag.prompts import JUDGE_PROMPT, JUDGE_SYSTEM
from legal_rag.query.models import AuditEntry, JudgeVerdict, RetrievedChunk

logger = logging.getLogger(__name__)


async def judge_relevance(
    question: str,
    chunks: list[RetrievedChunk],
    confidence_threshold: float = 0.85,
) -> tuple[JudgeVerdict, AuditEntry]:
    """Evaluate whether retrieved chunks are sufficient to answer.

    Returns:
        (JudgeVerdict, AuditEntry)
    """
    start = time.time()

    if not chunks:
        verdict = JudgeVerdict(
            relevant=False,
            sufficient=False,
            confidence=0.0,
            missing_info=["Không tìm được tài liệu pháp lý nào"],
            retry_required=True,
            retry_strategy="expand_query",
            reasoning="Không có tài liệu nào được truy xuất",
        )
        audit = AuditEntry(
            step="judge",
            status="success",
            duration_ms=(time.time() - start) * 1000,
            input_summary="0 chunks",
            output_summary="No chunks → retry required",
        )
        return verdict, audit

    try:
        # Build context string for judge
        context = _build_judge_context(chunks)

        prompt = JUDGE_PROMPT.format(
            question=question,
            context=context,
        )

        raw = await vllm_complete(
            prompt=prompt,
            system_prompt=JUDGE_SYSTEM,
            max_tokens=512,
            temperature=0.05,
        )

        verdict = _parse_judge_response(raw, confidence_threshold)

        duration_ms = (time.time() - start) * 1000
        audit = AuditEntry(
            step="judge",
            status="success",
            duration_ms=duration_ms,
            input_summary=f"{len(chunks)} chunks, question: {question[:100]}",
            output_summary=(
                f"relevant={verdict.relevant}, sufficient={verdict.sufficient}, "
                f"confidence={verdict.confidence:.2f}, retry={verdict.retry_required}"
            ),
            details={
                "relevant": verdict.relevant,
                "sufficient": verdict.sufficient,
                "confidence": verdict.confidence,
                "retry_required": verdict.retry_required,
                "retry_strategy": verdict.retry_strategy,
                "missing_info": verdict.missing_info,
                "coverage_score": verdict.coverage_score,
                "missing_clauses": verdict.missing_clauses,
                "missing_references": verdict.missing_references,
            },
        )

        logger.info(
            "Judge verdict: relevant=%s, sufficient=%s, confidence=%.2f, retry=%s",
            verdict.relevant,
            verdict.sufficient,
            verdict.confidence,
            verdict.retry_required,
        )
        return verdict, audit

    except Exception as e:
        duration_ms = (time.time() - start) * 1000
        logger.warning("Judge failed, assuming sufficient: %s", e)

        # Fallback: assume chunks are good enough (conservative)
        verdict = JudgeVerdict(
            relevant=True,
            sufficient=True,
            confidence=0.7,
            retry_required=False,
            reasoning=f"Judge error, defaulting to proceed: {str(e)[:100]}",
        )
        audit = AuditEntry(
            step="judge",
            status="failure",
            duration_ms=duration_ms,
            output_summary=f"Judge error, defaulting to proceed: {str(e)[:100]}",
        )
        return verdict, audit


def _build_judge_context(chunks: list[RetrievedChunk]) -> str:
    """Build a concise context string for the judge, including coverage analysis."""
    parts = []
    for i, chunk in enumerate(chunks[:15], 1):  # Max 15 chunks for judge
        meta_parts = []
        if chunk.doc_number:
            meta_parts.append(chunk.doc_number)
        if chunk.article:
            meta_parts.append(chunk.article)
        if chunk.clause:
            meta_parts.append(chunk.clause)

        meta_str = " | ".join(meta_parts) if meta_parts else f"chunk_{i}"
        text_preview = chunk.text[:500]
        score_str = f"score={chunk.score:.3f}"
        if chunk.rerank_score is not None:
            score_str += f", rerank={chunk.rerank_score:.3f}"

        parts.append(f"[{i}] ({meta_str}) ({score_str})\n{text_preview}")

    context = "\n\n---\n\n".join(parts)

    # Append coverage analysis summary
    coverage_summary = _build_coverage_summary(chunks[:15])
    if coverage_summary:
        context += f"\n\n{'='*60}\nPHÂN TÍCH ĐỘ BAO PHỦ:\n{coverage_summary}"

    return context


def _build_coverage_summary(chunks: list[RetrievedChunk]) -> str:
    """Analyze clause/reference coverage and return a summary string.

    Identifies:
      - Which Điều/Khoản/Điểm are present
      - Gaps in clause numbering (e.g., Khoản 1,3 but missing Khoản 2)
      - Cross-references mentioned but not retrieved
    """
    # Group by doc_number → article → clauses
    doc_articles: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for chunk in chunks:
        if chunk.doc_number and chunk.article:
            clause_key = chunk.clause or ""
            doc_articles[chunk.doc_number][chunk.article].append(clause_key)

    lines: list[str] = []

    for doc_num, articles in doc_articles.items():
        for article, clauses in articles.items():
            # Filter non-empty clauses and extract numbers
            clause_nums = set()
            for c in clauses:
                match = re.search(r"Khoản\s+(\d+)", c, re.IGNORECASE)
                if match:
                    clause_nums.add(int(match.group(1)))

            if clause_nums:
                min_k = min(clause_nums)
                max_k = max(clause_nums)
                expected = set(range(min_k, max_k + 1))
                missing = expected - clause_nums

                if missing:
                    missing_str = ", ".join(f"Khoản {k}" for k in sorted(missing))
                    lines.append(
                        f"- {doc_num} {article}: có Khoản "
                        f"{','.join(str(k) for k in sorted(clause_nums))} "
                        f"— THIẾU {missing_str}"
                    )

    # Check for cross-references mentioned in chunk texts but not retrieved
    all_articles = set()
    for doc_num, articles in doc_articles.items():
        for art in articles:
            all_articles.add((doc_num, art))

    ref_pattern = re.compile(
        r"(?:theo|tại|căn cứ)\s+Điều\s+(\d+[a-z]?)",
        re.IGNORECASE | re.UNICODE,
    )
    missing_refs: set[str] = set()
    for chunk in chunks:
        if not chunk.doc_number:
            continue
        for match in ref_pattern.finditer(chunk.text):
            ref_art = f"Điều {match.group(1)}"
            if (chunk.doc_number, ref_art) not in all_articles:
                missing_refs.add(f"{chunk.doc_number} {ref_art}")

    if missing_refs:
        for ref in sorted(missing_refs)[:5]:
            lines.append(f"- Tham chiếu chưa truy xuất: {ref}")

    return "\n".join(lines) if lines else ""


def _parse_judge_response(
    raw: str, confidence_threshold: float
) -> JudgeVerdict:
    """Parse JSON response from LLM Judge."""
    # Strip markdown code fences
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError("No JSON found in judge response")

        confidence = float(data.get("confidence", 0.5))
        relevant = bool(data.get("relevant", False))
        sufficient = bool(data.get("sufficient", False))
        missing_info = data.get("missing_info", [])
        retry_strategy = data.get("retry_strategy", "")
        reasoning = data.get("reasoning", "")

        # Determine if retry is needed
        retry_required = bool(data.get("retry_required", False))
        if not retry_required and confidence < confidence_threshold:
            retry_required = True
            if not retry_strategy:
                retry_strategy = "expand_query"

        return JudgeVerdict(
            relevant=relevant,
            sufficient=sufficient,
            confidence=confidence,
            missing_info=missing_info if isinstance(missing_info, list) else [str(missing_info)],
            retry_required=retry_required,
            retry_strategy=retry_strategy,
            reasoning=reasoning,
            # Phase 2: coverage analysis fields
            coverage_score=float(data.get("coverage_score", 0.0)),
            missing_clauses=data.get("missing_clauses", []),
            missing_references=data.get("missing_references", []),
        )

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning("Failed to parse judge JSON: %s — raw: %s", e, raw[:200])
        # Conservative fallback: mark as needing attention but don't retry
        return JudgeVerdict(
            relevant=True,
            sufficient=True,
            confidence=0.7,
            retry_required=False,
            reasoning=f"JSON parse failed, defaulting to proceed: {str(e)[:80]}",
        )
