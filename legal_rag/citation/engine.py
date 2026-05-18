"""Citation Engine — gắn citation chính xác đến từng dòng.

Giống NotebookLM: mỗi thông tin pháp lý trong câu trả lời
đều có dẫn chứng cụ thể đến điều/khoản/trang/dòng.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class Citation:
    doc_number: str
    doc_type: str
    issuer: str
    issue_date: str
    article: str
    clause: str
    point: str
    page_number: int
    line_start: int
    line_end: int
    excerpt: str
    relevance_score: float
    chunk_id: str

    def format_inline(self, index: int) -> str:
        """[^1] format cho inline citation."""
        return f"[^{index}]"

    def format_full(self, index: int) -> str:
        """Format đầy đủ cho phần References cuối."""
        location = self.article
        if self.clause:
            location += f", {self.clause}"
        if self.point:
            location += f", {self.point}"

        lines = [
            f"**[{index}] {self.doc_type} số {self.doc_number}**",
            f"  Cơ quan ban hành: {self.issuer}",
            f"  Ngày ban hành: {self.issue_date}",
            f"  Vị trí: {location}",
        ]
        if self.page_number:
            lines.append(f"  Trang {self.page_number}, dòng {self.line_start}–{self.line_end}")
        if self.excerpt:
            excerpt = self.excerpt[:150].replace("\n", " ")
            lines.append(f'  > "{excerpt}..."')
        return "\n".join(lines)


class CitationEngine:
    """Tích hợp citation vào câu trả lời từ LLM."""

    def build_citations(self, retrieved_chunks: list[dict]) -> list[Citation]:
        citations = []
        for chunk in retrieved_chunks:
            citations.append(Citation(
                doc_number=chunk.get("doc_number", ""),
                doc_type=chunk.get("doc_type", "Văn bản"),
                issuer=chunk.get("issuer", ""),
                issue_date=chunk.get("issue_date", ""),
                article=chunk.get("article", ""),
                clause=chunk.get("clause", ""),
                point=chunk.get("point", ""),
                page_number=chunk.get("page_number", 0),
                line_start=chunk.get("line_start", 0),
                line_end=chunk.get("line_end", 0),
                excerpt=(chunk.get("text") or chunk.get("content", ""))[:150].strip(),
                relevance_score=chunk.get("score", 0.0),
                chunk_id=chunk.get("chunk_id", ""),
            ))
        return citations

    def attach_references_section(
        self,
        answer: str,
        citations: list[Citation],
    ) -> str:
        """Thêm phần References cuối câu trả lời."""
        if not citations:
            return answer

        refs = "\n\n---\n### 📎 Tài liệu tham khảo\n\n"
        for i, c in enumerate(citations, 1):
            refs += c.format_full(i) + "\n\n"
        return answer.rstrip() + refs

    def build_context_with_ids(self, chunks: list[dict]) -> str:
        """Sinh context string có chunk_id để LLM dùng làm SOURCE placeholder."""
        parts = []
        for i, chunk in enumerate(chunks, 1):
            text = chunk.get("text") or chunk.get("content", "")
            article = chunk.get("article", "")
            clause = chunk.get("clause", "")
            doc_number = chunk.get("doc_number", "")
            location = f"{article}{', ' + clause if clause else ''} — {doc_number}"
            chunk_id = chunk.get("chunk_id", f"chunk_{i}")
            parts.append(f"[SOURCE:{chunk_id}] ({location})\n{text}")
        return "\n\n---\n\n".join(parts)


# System prompt yêu cầu LLM gắn citation placeholder
CITATION_SYSTEM_PROMPT = """\
Bạn là chuyên gia tư vấn pháp luật Việt Nam chuyên nghiệp.

QUY TẮC BẮT BUỘC:
- Chỉ sử dụng thông tin trong phần CONTEXT bên dưới
- Sau mỗi thông tin pháp lý, chèn placeholder: [SOURCE:chunk_id]
- chunk_id được cung cấp trong phần CONTEXT (dạng [SOURCE:xxx])
- Mỗi câu có thông tin pháp lý = phải có ít nhất 1 citation
- KHÔNG đưa thông tin không có trong CONTEXT

Ví dụ:
"Theo quy định, hợp đồng lao động phải được giao kết bằng văn bản [SOURCE:abc123].
Thời gian thử việc không quá 60 ngày [SOURCE:def456]."
"""
