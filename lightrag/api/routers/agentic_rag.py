"""
Agentic RAG pipeline for Vietnamese legal question answering.

Pipeline:
  1. Query Analysis — LLM rewrites query into formal legal Vietnamese, extracts
     domain keywords, detects if the question is multi-part.
  2. Retrieval — single enriched retrieval for simple questions; parallel
     sub-question retrievals for complex ones.
  3. Neighboring chunk expansion — after retrieval, fetches sibling chunks
     (±NEIGHBOR_WINDOW positions in same document) to avoid missing sub-items
     like "mục 2.f" when "mục 2.a–2.e" are already retrieved.
  4. Synthesis — if extra chunks found, builds a merged-context prompt and
     calls the LLM once; otherwise passes through to existing aquery_llm.

All steps yield NDJSON lines compatible with the existing /query/stream format:
  {"agentic_step": "analyzing"|"rewriting"|"retrieving"|"synthesizing", ...}
  {"references": [...]}   (placeholder first, then final grounded list)
  {"response": "chunk"}
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from functools import partial
from typing import Any, AsyncGenerator

import json_repair

from lightrag.base import QueryParam
from lightrag.utils import logger


# ── Constants ─────────────────────────────────────────────────────────────────

NEIGHBOR_WINDOW = 8          # chunks ±N around each retrieved chunk (wider for multi-item legal sections)
AGENTIC_CHUNK_TOP_K = 60     # higher retrieval ceiling in agentic mode
AGENTIC_SYNTHESIS_MAX = 40   # cap chunks fed to synthesis LLM
CHUNK_CONTENT_LIMIT = 2500   # chars per chunk in synthesis context
SYNTHESIS_CONTEXT_LIMIT = 60_000  # total chars in synthesis context (~15k tokens, safe for most models)
ROUND2_TRIGGER = 15          # if round-1 yields fewer chunks, trigger content-driven round-2

# Regex to strip non-Vietnamese/Latin garbage (CJK, Arabic, Cyrillic, etc.)
# These appear as OCR artifacts in scanned Vietnamese legal documents.
_GARBAGE_RE = re.compile(
    r'[一-鿿㐀-䶿'   # CJK Unified Ideographs
    r'؀-ۿݐ-ݿ'    # Arabic
    r'Ѐ-ӿ'                  # Cyrillic
    r'぀-ヿ'                  # Hiragana / Katakana
    r'가-힯'                  # Hangul
    r']+',
    re.UNICODE,
)


# ── Helpers (content cleaning) ────────────────────────────────────────────────

def _clean_content(text: str) -> str:
    """Strip OCR garbage characters and normalize whitespace."""
    text = _GARBAGE_RE.sub(' ', text)
    # Collapse runs of whitespace left after removal
    text = re.sub(r'[ \t]{3,}', ' ', text)
    text = re.sub(r'\n{4,}', '\n\n', text)
    return text.strip()


# ── Prompts ───────────────────────────────────────────────────────────────────

_ANALYSIS_PROMPT = """\
Bạn là chuyên gia pháp lý Việt Nam. Phân tích câu hỏi sau đây.
{history_context}
Câu hỏi: {query}

Trả về JSON (không có backtick, không giải thích):
{{
  "rewritten_query": "câu hỏi viết lại đầy đủ, chính xác",
  "search_queries": [
    "cụm từ khóa ngắn gọn phục vụ tìm kiếm vector (không có cú pháp hỏi)",
    "câu ngắn theo văn phong báo cáo/văn bản hành chính mô tả nội dung cần tìm"
  ],
  "hl_keywords": ["lĩnh vực pháp lý", "loại văn bản", "chủ đề chính"],
  "ll_keywords": ["số văn bản", "điều khoản cụ thể", "tên khái niệm pháp lý"],
  "is_complex": false,
  "sub_questions": []
}}

Quy tắc:
- rewritten_query: đủ ý, dùng thuật ngữ pháp lý/hành chính chính thức Việt Nam.
- search_queries[0]: chỉ từ khóa cốt lõi, không có "là gì", "như thế nào", "quy định" — dùng để embedding search.
- search_queries[1]: đoạn văn ngắn theo phong cách báo cáo hoặc văn bản hành chính, phù hợp với loại tài liệu chứa câu trả lời (số liệu, thống kê, đặc điểm, quy định nội bộ...).
- hl_keywords: 2-4 khái niệm/lĩnh vực bao quát.
- ll_keywords: 2-5 chi tiết cụ thể (số luật, điều khoản, tên khái niệm, địa danh, số liệu).
- is_complex = true CHỈ KHI câu hỏi cần tra cứu ít nhất 2 lĩnh vực/văn bản riêng biệt.
- sub_questions: điền khi is_complex=true, tối đa 3 câu, mỗi câu tập trung 1 khía cạnh.\
"""

_SYNTHESIS_SYSTEM = """\
Bạn là chuyên gia tư vấn pháp luật Việt Nam.
Dựa vào các đoạn văn bản pháp luật được cung cấp, hãy trả lời câu hỏi một cách chính xác, đầy đủ và có cấu trúc rõ ràng.

Nguyên tắc trả lời:
- Khai thác TỐI ĐA thông tin từ tất cả các đoạn trích được cung cấp, kể cả thông tin gián tiếp hoặc liên quan.
- Tổng hợp thông tin từ nhiều đoạn để đưa ra câu trả lời hoàn chỉnh nhất có thể.
- Nếu câu hỏi có nhiều phần, trả lời từng phần một cách rõ ràng.
- Chỉ ghi nhận "không tìm thấy thông tin" cho từng điểm CỤ THỂ khi tất cả các đoạn đều không đề cập — không áp dụng cho toàn bộ câu trả lời.
- Không từ chối trả lời khi có thông tin liên quan, dù chỉ là một phần.

Trích dẫn số tham chiếu [N] sau mỗi câu có thông tin pháp lý cụ thể.
Tạo phần "### Tài liệu tham khảo" ở cuối theo định dạng: * [N] Tên văn bản\
"""


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AgenticAnalysis:
    rewritten_query: str
    hl_keywords: list[str] = field(default_factory=list)
    ll_keywords: list[str] = field(default_factory=list)
    is_complex: bool = False
    sub_questions: list[str] = field(default_factory=list)
    search_queries: list[str] = field(default_factory=list)


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _analyze_query(
    query: str,
    llm_func,
    history: list[dict[str, Any]] | None = None,
) -> AgenticAnalysis:
    history_ctx = ""
    if history:
        recent = history[-4:]
        lines = "\n".join(
            f"{m['role'].title()}: {str(m.get('content', ''))[:200]}"
            for m in recent
        )
        history_ctx = f"\nLịch sử hội thoại gần đây:\n{lines}\n"

    prompt = _ANALYSIS_PROMPT.format(query=query, history_context=history_ctx)

    try:
        raw = await llm_func(prompt, stream=False)
        data: dict = json_repair.loads(raw)  # type: ignore[assignment]
        sub_qs = [str(q) for q in data.get("sub_questions", [])[:3] if str(q).strip()]
        search_qs = [str(q) for q in data.get("search_queries", [])[:3] if str(q).strip()]
        return AgenticAnalysis(
            rewritten_query=str(data.get("rewritten_query", query)).strip() or query,
            hl_keywords=[str(k) for k in data.get("hl_keywords", [])],
            ll_keywords=[str(k) for k in data.get("ll_keywords", [])],
            is_complex=bool(data.get("is_complex", False)),
            sub_questions=sub_qs,
            search_queries=search_qs,
        )
    except Exception as exc:
        logger.warning(f"[agentic] analyze_query failed ({exc}), using original query")
        return AgenticAnalysis(rewritten_query=query)


async def _fetch_neighbor_chunks(
    rag,
    retrieved_chunks: list[dict],
    window: int = NEIGHBOR_WINDOW,
) -> list[dict]:
    """
    For each retrieved chunk, fetch up to `window` chunks before/after it
    from the same document (same full_doc_id) that weren't already retrieved.

    Works with JSON KV storage (_data in-memory dict).
    Silently returns [] for other backends.
    """
    if not retrieved_chunks:
        return []

    storage = rag.text_chunks
    data_dict = getattr(storage, '_data', None)
    if not data_dict:
        return []

    # Collect the full_doc_ids of retrieved chunks
    target_doc_ids: set[str] = set()
    for c in retrieved_chunks:
        fid = c.get("full_doc_id", "")
        if fid:
            target_doc_ids.add(fid)

    if not target_doc_ids:
        return []

    # Build per-doc index from in-memory storage
    doc_chunk_index: dict[str, list[tuple[int, str, dict]]] = {}
    lock = getattr(storage, '_storage_lock', None)

    async def _build_index():
        for chunk_id, chunk_data in data_dict.items():
            fid = chunk_data.get("full_doc_id", "")
            if fid not in target_doc_ids:
                continue
            idx = chunk_data.get("chunk_order_index", 0)
            doc_chunk_index.setdefault(fid, []).append((idx, chunk_id, chunk_data))

    if lock:
        async with lock:
            await _build_index()
    else:
        await _build_index()

    for fid in doc_chunk_index:
        doc_chunk_index[fid].sort(key=lambda x: x[0])

    # Determine which chunk_order_indices were already retrieved per doc
    retrieved_ids: set[str] = set()
    retrieved_by_doc: dict[str, set[int]] = {}
    for c in retrieved_chunks:
        cid = c.get("chunk_id") or c.get("_id") or c.get("id", "")
        if cid:
            retrieved_ids.add(cid)
        fid = c.get("full_doc_id", "")
        if fid:
            oi = c.get("chunk_order_index", -1)
            retrieved_by_doc.setdefault(fid, set()).add(oi)

    neighbors: list[dict] = []
    seen = set(retrieved_ids)

    for fid, sorted_chunks in doc_chunk_index.items():
        target_indices = retrieved_by_doc.get(fid, set())
        for idx, cid, cdata in sorted_chunks:
            if cid in seen:
                continue
            for ri in target_indices:
                if abs(idx - ri) <= window:
                    seen.add(cid)
                    neighbors.append({
                        "chunk_id": cid,
                        "chunk_order_index": idx,
                        "content": cdata.get("content", ""),
                        "full_doc_id": fid,
                        "file_path": cdata.get("file_path", ""),
                        "tokens": cdata.get("tokens", 0),
                    })
                    break

    # Sort neighbors by (full_doc_id, chunk_order_index) for stable ordering
    neighbors.sort(key=lambda x: (x["full_doc_id"], x["chunk_order_index"]))
    return neighbors


def _build_synthesis_context(chunks: list[dict]) -> tuple[str, list[dict]]:
    """
    Number chunks 1..N, build context string and fully-enriched references list.
    Cleans OCR garbage and stops when total chars exceed SYNTHESIS_CONTEXT_LIMIT.
    Returns (context_str, references).
    """
    context_parts: list[str] = []
    references: list[dict] = []
    total_chars = 0

    for i, chunk in enumerate(chunks):
        raw = str(chunk.get("content", ""))
        content = _clean_content(raw)[:CHUNK_CONTENT_LIMIT]
        if not content:
            continue

        # Stop adding chunks once the context would exceed the safe token budget
        if total_chars + len(content) > SYNTHESIS_CONTEXT_LIMIT:
            logger.info(f"[agentic] context limit reached at chunk {i + 1}/{len(chunks)}")
            break

        ref_id = str(len(references) + 1)  # sequential based on included chunks
        fp = chunk.get("file_path", "")
        cid = chunk.get("chunk_id") or chunk.get("_id") or chunk.get("id", "")
        context_parts.append(f"[{ref_id}] {content}")
        references.append({
            "reference_id": ref_id,
            "file_path": fp,
            "chunk_id": cid,
            "chunk_order_index": chunk.get("chunk_order_index", 0),
            "content": [content] if content else [],
        })
        total_chars += len(content)

    return "\n\n".join(context_parts), references


def _merge_data(results: list[dict[str, Any]]) -> tuple[list[dict], list[dict]]:
    """Deduplicate and merge chunks + references from multiple aquery_data calls."""
    seen_chunks: set[str] = set()
    seen_refs: set[str] = set()
    chunks: list[dict] = []
    refs: list[dict] = []

    for result in results:
        data = result.get("data", {})
        for chunk in data.get("chunks", []):
            cid = chunk.get("chunk_id") or chunk.get("id", "")
            if cid and cid not in seen_chunks:
                seen_chunks.add(cid)
                chunks.append(chunk)
        for ref in data.get("references", []):
            rid = ref.get("reference_id", "")
            if rid and rid not in seen_refs:
                seen_refs.add(rid)
                refs.append(ref)

    return chunks, refs


async def _content_driven_expansion(
    rag,
    initial_chunks: list[dict],
    data_param: "QueryParam",
) -> list[dict]:
    """
    Round-2 retrieval: use the content of already-retrieved chunks as a new query
    to find semantically related chunks that the original query phrasing missed.

    Works best for hierarchical legal documents where adjacent sections use
    different vocabulary than the user's question (e.g. "mục 2.f" vs "trường hợp f").
    """
    if not initial_chunks:
        return []

    # Build a dense "mini-document" from the first few retrieved chunks
    # — this embeds closer to the document's own vocabulary
    seed_text = " ".join(
        str(c.get("content", ""))[:400]
        for c in initial_chunks[:5]
    ).strip()
    if not seed_text:
        return []

    # Use naive mode so it searches by chunk content, not KG entities
    from lightrag.base import QueryParam as QP
    naive_param = QP(
        mode="naive",
        chunk_top_k=data_param.chunk_top_k,
        stream=False,
    )

    try:
        result = await rag.aquery_data(seed_text[:600], naive_param)
        return result.get("data", {}).get("chunks", [])
    except Exception as exc:
        logger.warning(f"[agentic] content-driven expansion failed: {exc}")
        return []


async def _coverage_supplement(
    rag,
    chunks: list[dict],
    ll_keywords: list[str],
    data_param: "QueryParam",
) -> list[dict]:
    """
    Check whether ll_keywords from the analysis appear in the retrieved chunks.
    For each keyword that is NOT covered, do a targeted search.
    Returns new chunks (not already in `chunks`) that fill the gaps.
    """
    if not ll_keywords or not chunks:
        return []

    covered_text = " ".join(
        str(c.get("content", "")).lower() for c in chunks
    )

    missing = [kw for kw in ll_keywords if kw.lower() not in covered_text]
    if not missing:
        return []

    logger.info(f"[agentic] coverage gap — searching for: {missing}")
    gap_query = " ".join(missing[:5])

    from lightrag.base import QueryParam as QP
    gap_param = QP(
        mode="naive",
        chunk_top_k=data_param.chunk_top_k,
        stream=False,
    )

    try:
        result = await rag.aquery_data(gap_query, gap_param)
        new_chunks = result.get("data", {}).get("chunks", [])
        existing_ids = {
            c.get("chunk_id") or c.get("_id") or c.get("id", "")
            for c in chunks
        }
        return [
            c for c in new_chunks
            if (c.get("chunk_id") or c.get("_id") or c.get("id", "")) not in existing_ids
        ]
    except Exception as exc:
        logger.warning(f"[agentic] coverage supplement failed: {exc}")
        return []


async def _stream_synthesis(
    query: str,
    all_chunks: list[dict],
    rag,
    param: QueryParam,
    include_refs: bool,
) -> AsyncGenerator[str, None]:
    """
    Build context from all_chunks, call LLM in bypass mode, stream results.
    Yields NDJSON lines: {"response": ...} and {"references": ...}.
    Only cited references are included in the final references line.
    """
    context_str, references = _build_synthesis_context(all_chunks)
    synthesis_query = (
        f"Các văn bản pháp luật tham khảo:\n\n{context_str}\n\n"
        f"---Câu hỏi người dùng---\n{query}"
    )

    bypass_param = QueryParam(
        mode="bypass",
        stream=True,
        conversation_history=param.conversation_history,
    )

    if include_refs:
        yield json.dumps({"references": []}) + "\n"

    result = await rag.aquery_llm(synthesis_query, param=bypass_param, system_prompt=_SYNTHESIS_SYSTEM)
    llm_resp = result.get("llm_response", {})

    full_parts: list[str] = []
    if llm_resp.get("is_streaming"):
        async for chunk in llm_resp.get("response_iterator"):
            if chunk:
                full_parts.append(chunk)
                yield json.dumps({"response": chunk}) + "\n"
    else:
        content = llm_resp.get("content", "")
        if content:
            full_parts.append(content)
            yield json.dumps({"response": content}) + "\n"

    if include_refs:
        # Filter to only references actually cited in the response text
        full_text = "".join(full_parts)
        cited_ids = {m.group(1) for m in re.finditer(r'\[(\d+)\]', full_text)}
        refs_by_id = {str(r.get("reference_id", "")): r for r in references}
        grounded = [refs_by_id[rid] for rid in sorted(cited_ids, key=lambda x: int(x) if x.isdigit() else 0) if rid in refs_by_id]
        yield json.dumps({"references": grounded}) + "\n"


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def agentic_query_stream(
    query: str,
    rag,
    param: QueryParam,
    include_refs: bool = True,
    include_chunk_content: bool = False,
) -> AsyncGenerator[str, None]:
    """
    Yields NDJSON lines:
      {"agentic_step": str, ...}   — progress events
      {"references": [...]}        — reference list
      {"response": str}            — answer chunks
    """
    llm_func = partial(rag.llm_model_func, _priority=5)

    # ── Step 1: Analyze ───────────────────────────────────────────────────────
    yield json.dumps({"agentic_step": "analyzing", "message": "Đang phân tích câu hỏi…"}) + "\n"

    analysis = await _analyze_query(query, llm_func, param.conversation_history)

    logger.info(
        f"[agentic] rewritten='{analysis.rewritten_query}' "
        f"complex={analysis.is_complex} sub_q={analysis.sub_questions}"
    )

    yield json.dumps({
        "agentic_step": "rewriting",
        "rewritten": analysis.rewritten_query,
        "keywords": analysis.hl_keywords[:4],
    }) + "\n"

    # ── Step 2: Decide retrieval strategy ────────────────────────────────────
    use_multi_hop = analysis.is_complex and len(analysis.sub_questions) >= 2

    if use_multi_hop:
        # ── Multi-hop retrieval ───────────────────────────────────────────────
        yield json.dumps({
            "agentic_step": "retrieving",
            "message": f"Đang tra cứu {len(analysis.sub_questions)} khía cạnh…",
            "sub_questions": analysis.sub_questions,
        }) + "\n"

        data_param = QueryParam(
            mode=param.mode,
            top_k=param.top_k,
            chunk_top_k=AGENTIC_CHUNK_TOP_K,
            enable_rerank=param.enable_rerank,
        )
        raw_results = await asyncio.gather(
            *[rag.aquery_data(sq, data_param) for sq in analysis.sub_questions],
            return_exceptions=True,
        )
        valid: list[dict] = [r for r in raw_results if isinstance(r, dict)]
        merged_chunks, _ = _merge_data(valid)

        if merged_chunks:
            # Expand with neighboring chunks
            extra = await _fetch_neighbor_chunks(rag, merged_chunks)
            if extra:
                logger.info(f"[agentic] multi-hop: +{len(extra)} neighbor chunks")

            all_chunks = _deduplicate_chunks(merged_chunks + extra)[:AGENTIC_SYNTHESIS_MAX]

            yield json.dumps({"agentic_step": "synthesizing", "message": "Đang tổng hợp câu trả lời…"}) + "\n"
            async for line in _stream_synthesis(query, all_chunks, rag, param, include_refs):
                yield line
            return

        logger.warning("[agentic] multi-hop retrieved no chunks, falling back to simple path")

    # ── Simple path ───────────────────────────────────────────────────────────
    yield json.dumps({"agentic_step": "retrieving", "message": "Đang tìm kiếm văn bản liên quan…"}) + "\n"

    # Use higher chunk_top_k for numbered-section queries
    adaptive_chunk_top_k = AGENTIC_CHUNK_TOP_K
    if param.chunk_top_k and param.chunk_top_k > AGENTIC_CHUNK_TOP_K:
        adaptive_chunk_top_k = param.chunk_top_k

    data_param = QueryParam(
        mode=param.mode,
        top_k=param.top_k,
        chunk_top_k=adaptive_chunk_top_k,
        hl_keywords=analysis.hl_keywords or param.hl_keywords,
        ll_keywords=analysis.ll_keywords or param.ll_keywords,
        stream=False,
        enable_rerank=param.enable_rerank,
        conversation_history=param.conversation_history,
        user_prompt=param.user_prompt,
        response_type=param.response_type,
    )

    # Run rewritten_query + search_queries (keyword-dense + report-style) in parallel.
    # This covers the case where the answer is in a factual/statistical document that
    # embeds far from a formally-phrased legal question.
    retrieval_queries = [analysis.rewritten_query] + (analysis.search_queries or [])
    retrieval_queries = list(dict.fromkeys(q for q in retrieval_queries if q))[:4]

    if len(retrieval_queries) > 1:
        raw_results = await asyncio.gather(
            *[rag.aquery_data(q, data_param) for q in retrieval_queries],
            return_exceptions=True,
        )
        valid = [r for r in raw_results if isinstance(r, dict)]
        initial_chunks, _ = _merge_data(valid)
        logger.info(
            f"[agentic] multi-query simple: {len(retrieval_queries)} queries → {len(initial_chunks)} chunks"
        )
    else:
        data_result = await rag.aquery_data(analysis.rewritten_query, data_param)
        initial_chunks = data_result.get("data", {}).get("chunks", [])

    # Round-2: content-driven expansion when initial retrieval is thin.
    # Use retrieved chunks' own text as a query to find related chunks the
    # original phrasing couldn't reach (different vocabulary, section headers, etc.).
    if 0 < len(initial_chunks) < ROUND2_TRIGGER:
        round2 = await _content_driven_expansion(rag, initial_chunks, data_param)
        if round2:
            before = len(initial_chunks)
            initial_chunks = _deduplicate_chunks(initial_chunks + round2)
            logger.info(f"[agentic] round-2 expansion: {before} → {len(initial_chunks)} chunks")

    # Coverage supplement: search specifically for ll_keywords not yet found in chunks.
    # Catches the case where a specific law number / clause is mentioned in the query
    # but no retrieved chunk contains it yet.
    if analysis.ll_keywords:
        supplement = await _coverage_supplement(
            rag, initial_chunks, analysis.ll_keywords, data_param
        )
        if supplement:
            initial_chunks = _deduplicate_chunks(initial_chunks + supplement)
            logger.info(f"[agentic] coverage supplement: +{len(supplement)} chunks")

    # Expand with neighboring chunks from same document
    extra = await _fetch_neighbor_chunks(rag, initial_chunks)
    if extra:
        logger.info(
            f"[agentic] simple path: {len(initial_chunks)} retrieved + {len(extra)} neighbors"
        )

    # Enter synthesis path when multi-query or neighbor expansion found useful chunks.
    # Cap at AGENTIC_SYNTHESIS_MAX to prevent context explosion.
    use_synthesis = bool(extra) or (len(retrieval_queries) > 1 and len(initial_chunks) >= 3)
    if use_synthesis:
        all_chunks = _deduplicate_chunks(initial_chunks + extra)[:AGENTIC_SYNTHESIS_MAX]
        yield json.dumps({"agentic_step": "synthesizing", "message": "Đang tổng hợp câu trả lời…"}) + "\n"
        async for line in _stream_synthesis(query, all_chunks, rag, param, include_refs):
            yield line
        return

    # No extra chunks found — use aquery_llm (full pipeline with KG context)
    yield json.dumps({"agentic_step": "synthesizing", "message": "Đang tổng hợp câu trả lời…"}) + "\n"

    enhanced_param = QueryParam(
        mode=param.mode,
        top_k=param.top_k,
        chunk_top_k=adaptive_chunk_top_k,
        hl_keywords=analysis.hl_keywords or param.hl_keywords,
        ll_keywords=analysis.ll_keywords or param.ll_keywords,
        stream=True,
        enable_rerank=param.enable_rerank,
        conversation_history=param.conversation_history,
        user_prompt=param.user_prompt,
        response_type=param.response_type,
    )

    result = await rag.aquery_llm(analysis.rewritten_query, param=enhanced_param)
    llm_resp = result.get("llm_response", {})

    if include_refs:
        yield json.dumps({"references": []}) + "\n"

    full_parts: list[str] = []
    if llm_resp.get("is_streaming"):
        async for chunk in llm_resp.get("response_iterator"):
            if chunk:
                full_parts.append(chunk)
                yield json.dumps({"response": chunk}) + "\n"
    else:
        content = llm_resp.get("content", "")
        if content:
            full_parts.append(content)
            yield json.dumps({"response": content}) + "\n"

    if include_refs:
        from lightrag.api.routers.query_routes import (
            _enrich_references_with_chunk_metadata,
            _filter_references_by_citations,
        )
        references = await _enrich_references_with_chunk_metadata(
            rag, result.get("data", {}), include_chunk_content=include_chunk_content
        )
        grounded = _filter_references_by_citations("".join(full_parts), references)
        yield json.dumps({"references": grounded}) + "\n"


def _deduplicate_chunks(chunks: list[dict]) -> list[dict]:
    """Remove duplicate chunks by chunk_id, preserving order."""
    seen: set[str] = set()
    out: list[dict] = []
    for c in chunks:
        cid = c.get("chunk_id") or c.get("_id") or c.get("id", "")
        if cid and cid in seen:
            continue
        if cid:
            seen.add(cid)
        out.append(c)
    return out
