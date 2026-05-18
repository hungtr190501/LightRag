from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional


@dataclass
class LegalChunk:
    """Đơn vị lưu trữ cơ bản cho văn bản pháp lý.

    Hỗ trợ parent/child hierarchy (Điều → Khoản → Điểm) và contextual header.
    """

    # === ĐỊNH DANH ===
    chunk_id: str
    doc_id: str
    chunk_level: Literal["parent", "child"] = "child"
    parent_id: Optional[str] = None

    # === NỘI DUNG ===
    # text: văn bản đã prepend contextual header (dùng để embed)
    # original_text: văn bản gốc (dùng cho citation)
    text: str = ""
    original_text: str = ""

    # === VỊ TRÍ CHÍNH XÁC ===
    page_number: int = 0
    line_start: int = 0
    line_end: int = 0
    char_start: int = 0
    char_end: int = 0

    # === THÔNG TIN VĂN BẢN PHÁP LÝ ===
    doc_number: str = ""        # "23/2023/NĐ-CP"
    doc_type: str = ""          # "Nghị định" | "Thông tư" | "Luật" ...
    issuer: str = ""
    issue_date: str = ""
    effective_date: str = ""
    article: Optional[str] = None   # "Điều 5"
    clause: Optional[str] = None    # "Khoản 2"
    point: Optional[str] = None     # "Điểm a"

    # === LEGAL STATUS & AUTHORITY ===
    # Trạng thái hiệu lực: HIEU_LUC | HET_HIEU_LUC | BI_THAY_THE | SAP_HIEU_LUC
    status: str = "HIEU_LUC"
    # True = điều luật chính thức; False = FAQ, blog, bình luận, giải thích phụ
    is_primary_source: bool = True
    # Pre-computed scores (0-1), set by legal_scorer; stored in payload for transparency
    legal_priority: float = 0.0
    authority_score: float = 0.0

    # === VECTOR EMBEDDING (populated by embedder) ===
    embedding: Optional[list[float]] = field(default=None, repr=False)
    sparse_embedding: Optional[dict] = field(default=None, repr=False)

    def to_payload(self) -> dict:
        """Convert to Qdrant payload dict (no vectors)."""
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "chunk_level": self.chunk_level,
            "parent_id": self.parent_id,
            "text": self.original_text or self.text,
            "page_number": self.page_number,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "doc_number": self.doc_number,
            "doc_type": self.doc_type,
            "issuer": self.issuer,
            "issue_date": self.issue_date,
            "effective_date": self.effective_date,
            "article": self.article,
            "clause": self.clause,
            "point": self.point,
            "status": self.status,
            "is_primary_source": self.is_primary_source,
            "legal_priority": self.legal_priority,
            "authority_score": self.authority_score,
        }
