from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DocumentMeta:
    """Metadata của một văn bản pháp quy."""

    doc_id: str
    doc_number: str         # "23/2023/NĐ-CP"
    doc_type: str           # "Nghị định" | "Thông tư" | "Luật" | "Quyết định"
    title: str
    issuer: str             # "Chính phủ" | "Bộ Công an" | ...
    issue_date: str         # "2023-04-28" ISO format
    effective_date: str = ""
    expiry_date: Optional[str] = None
    legal_domain: list[str] = field(default_factory=list)
    source_file: str = ""   # original file path
    doc_url: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "DocumentMeta":
        return cls(
            doc_id=d["doc_id"],
            doc_number=d.get("doc_number", ""),
            doc_type=d.get("doc_type", "Văn bản"),
            title=d.get("title", ""),
            issuer=d.get("issuer", ""),
            issue_date=d.get("issue_date", ""),
            effective_date=d.get("effective_date", ""),
            expiry_date=d.get("expiry_date"),
            legal_domain=d.get("legal_domain", []),
            source_file=d.get("source_file", ""),
            doc_url=d.get("doc_url", ""),
        )

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "doc_number": self.doc_number,
            "doc_type": self.doc_type,
            "title": self.title,
            "issuer": self.issuer,
            "issue_date": self.issue_date,
            "effective_date": self.effective_date,
            "expiry_date": self.expiry_date,
            "legal_domain": self.legal_domain,
            "source_file": self.source_file,
            "doc_url": self.doc_url,
        }
