"""Tầng 3 — Contextual Header Generator.

Mỗi chunk được prepend 1-2 câu context do LLM sinh ra.
Chunk "tự biết" nó thuộc văn bản nào, điều chỉnh gì — kể cả khi retrieved độc lập.

Dùng vLLM batch để tối ưu throughput (continuous batching).
"""
from __future__ import annotations

from legal_rag.llm.vllm_adapter import vllm_batch_complete
from legal_rag.models.chunk import LegalChunk

_SYSTEM_PROMPT = (
    "Bạn là trợ lý phân tích văn bản pháp luật Việt Nam. "
    "Viết 1 câu ngắn đặt đoạn văn vào ngữ cảnh (số hiệu, loại văn bản, chủ đề). "
    "Chỉ trả về câu context, không giải thích thêm."
)

# Giới hạn chars: doc_header ~150 chars ≈ 150-300 tokens; chunk_text ~300 chars ≈ 300-600 tokens
# Tổng ước tính: system(~40t) + template_structure(~60t) + header(~300t) + chunk(~600t) ≈ 1000t
# → an toàn với max_context=4096 kể cả Vietnamese tokenizer nặng nhất
_MAX_DOC_HEADER_CHARS = 150
_MAX_CHUNK_CHARS = 300

_PROMPT_TEMPLATE = """\
Văn bản gốc (phần đầu):
<doc_header>
{doc_header}
</doc_header>

Đoạn cần đặt context:
<chunk>
{chunk_text}
</chunk>

Vị trí: {location} của {doc_type} số {doc_number} do {issuer} ban hành ngày {issue_date}.

Viết 1-2 câu context ngắn gọn:"""


async def add_contextual_headers(
    chunks: list[LegalChunk],
    doc_header: str,
    doc_meta: dict,
    batch_size: int = 16,
) -> list[LegalChunk]:
    """Sinh contextual header cho toàn bộ chunks của một document.

    Kết quả: chunk.text = "[CONTEXT] {header}\\n[NỘI DUNG] {original_text}"
    chunk.original_text giữ nguyên text gốc (dùng cho citation).
    """
    prompts = []
    for chunk in chunks:
        location_parts = [chunk.article or ""]
        if chunk.clause:
            location_parts.append(chunk.clause)
        location = ", ".join(p for p in location_parts if p) or "Toàn văn"

        prompt = _PROMPT_TEMPLATE.format(
            doc_header=doc_header[:_MAX_DOC_HEADER_CHARS],
            chunk_text=(chunk.original_text or chunk.text)[:_MAX_CHUNK_CHARS],
            location=location,
            doc_type=doc_meta.get("doc_type", "Văn bản"),
            doc_number=doc_meta.get("doc_number", ""),
            issuer=doc_meta.get("issuer", ""),
            issue_date=doc_meta.get("issue_date", ""),
        )
        prompts.append(prompt)

    headers = await vllm_batch_complete(
        prompts=prompts,
        system_prompt=_SYSTEM_PROMPT,
        max_tokens=128,
        concurrency=batch_size,
    )

    enriched: list[LegalChunk] = []
    for chunk, header in zip(chunks, headers):
        header_clean = header.strip().rstrip(".")
        original = chunk.original_text or chunk.text
        # Nếu LLM trả rỗng (lỗi context / timeout), giữ nguyên text gốc
        enriched_text = (
            f"[CONTEXT] {header_clean}.\n[NỘI DUNG] {original}"
            if header_clean
            else original
        )
        enriched_chunk = LegalChunk(
            chunk_id=chunk.chunk_id,
            doc_id=chunk.doc_id,
            chunk_level=chunk.chunk_level,
            parent_id=chunk.parent_id,
            text=enriched_text,
            original_text=original,
            page_number=chunk.page_number,
            line_start=chunk.line_start,
            line_end=chunk.line_end,
            char_start=chunk.char_start,
            char_end=chunk.char_end,
            doc_number=chunk.doc_number,
            doc_type=chunk.doc_type,
            issuer=chunk.issuer,
            issue_date=chunk.issue_date,
            effective_date=chunk.effective_date,
            article=chunk.article,
            clause=chunk.clause,
            point=chunk.point,
        )
        enriched.append(enriched_chunk)

    return enriched
