"""Legal Query Rewriter — Step 1 of the pipeline.

Nhận câu hỏi thô từ user → mở rộng ngữ cảnh pháp lý, trích xuất
tham chiếu cụ thể, và xác định intent.
"""
from __future__ import annotations

import json
import logging
import re
import time
from typing import Optional

from legal_rag.llm.vllm_adapter import vllm_complete
from legal_rag.prompts import QUERY_REWRITE_PROMPT, QUERY_REWRITE_SYSTEM
from legal_rag.query.models import AuditEntry, RewrittenQuery

logger = logging.getLogger(__name__)

# Regex trích xuất tham chiếu pháp lý từ text (fallback khi LLM fail)
_REF_PATTERNS = [
    r"[Đđ]iều\s+\d+",
    r"[Kk]hoản\s+\d+",
    r"[Đđ]iểm\s+[a-zđ]",
    r"[Ll]uật\s+[A-ZĐÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬ][^\n,;.]{3,50}(?:\s+\d{4})?",
    r"\d{1,3}/\d{4}/(?:NĐ|TT|QĐ|CT|NQ|PL)-[A-ZĐẮẰẶẤẦẨẪẬ]+",
    r"[Nn]ghị\s+định\s+(?:số\s+)?\d+[^\n,;.]{0,30}",
    r"[Tt]hông\s+tư\s+(?:số\s+)?\d+[^\n,;.]{0,30}",
]
_COMPILED_REFS = [re.compile(p, re.UNICODE) for p in _REF_PATTERNS]


async def rewrite_query(
    question: str,
    conversation_history: Optional[list[dict]] = None,
) -> tuple[RewrittenQuery, AuditEntry]:
    """Rewrite user question for optimal legal retrieval.

    Returns:
        (RewrittenQuery, AuditEntry)
    """
    start = time.time()

    try:
        prompt = QUERY_REWRITE_PROMPT.format(question=question)
        raw = await vllm_complete(
            prompt=prompt,
            system_prompt=QUERY_REWRITE_SYSTEM,
            max_tokens=512,
            temperature=0.05,
        )

        result = _parse_rewrite_response(raw, question)

        duration_ms = (time.time() - start) * 1000
        audit = AuditEntry(
            step="query_rewrite",
            status="success",
            duration_ms=duration_ms,
            input_summary=question[:200],
            output_summary=result.rewritten[:200],
            details={
                "extracted_refs": result.extracted_refs,
                "keywords": result.keywords,
                "intent": result.intent,
            },
        )
        logger.info(
            "Query rewritten: '%s' → '%s' (refs=%d, keywords=%d)",
            question[:80],
            result.rewritten[:80],
            len(result.extracted_refs),
            len(result.keywords),
        )
        return result, audit

    except Exception as e:
        logger.warning("Query rewrite failed, using original: %s", e)
        duration_ms = (time.time() - start) * 1000

        # Fallback: use original + regex extraction
        fallback = RewrittenQuery(
            original=question,
            rewritten=question,
            extracted_refs=_extract_refs_regex(question),
            keywords=_extract_keywords_simple(question),
            intent="lookup",
        )
        audit = AuditEntry(
            step="query_rewrite",
            status="failure",
            duration_ms=duration_ms,
            input_summary=question[:200],
            output_summary=f"Fallback to original: {str(e)[:100]}",
        )
        return fallback, audit


def _parse_rewrite_response(raw: str, original: str) -> RewrittenQuery:
    """Parse LLM JSON response, with fallback."""
    # Strip markdown code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)

    try:
        # Try to find JSON object in the response
        json_match = re.search(r"\{[\s\S]*\}", cleaned)
        if json_match:
            data = json.loads(json_match.group())
        else:
            raise ValueError("No JSON found in response")

        return RewrittenQuery(
            original=original,
            rewritten=data.get("rewritten", original),
            extracted_refs=data.get("extracted_refs", []),
            keywords=data.get("keywords", []),
            intent=data.get("intent", "lookup"),
        )
    except (json.JSONDecodeError, ValueError) as e:
        logger.warning("Failed to parse rewrite JSON: %s", e)
        return RewrittenQuery(
            original=original,
            rewritten=original,
            extracted_refs=_extract_refs_regex(original),
            keywords=_extract_keywords_simple(original),
            intent="lookup",
        )


def _extract_refs_regex(text: str) -> list[str]:
    """Fallback: trích xuất tham chiếu pháp lý bằng regex."""
    refs: list[str] = []
    for pattern in _COMPILED_REFS:
        for match in pattern.finditer(text):
            ref = match.group().strip()
            if ref and ref not in refs:
                refs.append(ref)
    return refs


def _extract_keywords_simple(text: str) -> list[str]:
    """Fallback: trích xuất từ khóa đơn giản."""
    # Remove common Vietnamese stop words
    stop_words = {
        "là", "của", "và", "có", "được", "trong", "theo", "về",
        "cho", "với", "từ", "đến", "khi", "nếu", "thì", "mà",
        "các", "những", "một", "này", "đó", "tôi", "bạn", "hỏi",
        "gì", "nào", "sao", "như", "thế", "ra", "vào", "lên",
        "xuống", "qua", "lại", "đi", "rồi", "hay", "hoặc",
    }
    words = re.findall(r"[\w]+", text.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 1]
    # Deduplicate while preserving order
    seen: set[str] = set()
    unique = []
    for k in keywords:
        if k not in seen:
            seen.add(k)
            unique.append(k)
    return unique[:15]
