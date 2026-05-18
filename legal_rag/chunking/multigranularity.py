"""Tầng 2 — Multi-granularity Builder.

Từ cây LegalNode → 2 list chunks:
  - parent_chunks: mỗi Điều = 1 chunk (full text)
  - child_chunks:  mỗi Khoản = 1 chunk nhỏ (precision cao)

Strategy: retrieve bằng child, trả về parent khi generate.
"""
from __future__ import annotations

import hashlib

from legal_rag.chunking.structure_splitter import LegalNode
from legal_rag.models.chunk import LegalChunk


def build_parent_child_chunks(
    dieu_nodes: list[LegalNode],
    doc_meta: dict,
) -> tuple[list[LegalChunk], list[LegalChunk]]:
    """
    Args:
        dieu_nodes: output của StructureAwareSplitter.parse()
        doc_meta: dict với keys: doc_id, doc_number, doc_type, issuer,
                  issue_date, effective_date (optional)
    Returns:
        (parent_chunks, child_chunks)
    """
    parent_chunks: list[LegalChunk] = []
    child_chunks: list[LegalChunk] = []

    for dieu_node in dieu_nodes:
        parent_id = _make_id(doc_meta["doc_id"], dieu_node.label)

        parent = LegalChunk(
            chunk_id=parent_id,
            doc_id=doc_meta["doc_id"],
            chunk_level="parent",
            parent_id=None,
            text=dieu_node.full_text,
            original_text=dieu_node.full_text,
            page_number=dieu_node.page_start,
            line_start=dieu_node.line_start,
            line_end=dieu_node.line_end,
            char_start=dieu_node.char_start,
            char_end=dieu_node.char_end,
            doc_number=doc_meta["doc_number"],
            doc_type=doc_meta["doc_type"],
            issuer=doc_meta["issuer"],
            issue_date=doc_meta["issue_date"],
            effective_date=doc_meta.get("effective_date", ""),
            article=dieu_node.label,
            clause=None,
            point=None,
        )
        parent_chunks.append(parent)

        for khoan_node in dieu_node.children:
            child_id = _make_id(doc_meta["doc_id"], dieu_node.label, khoan_node.label)
            child_line_start = khoan_node.lines[0].global_line if khoan_node.lines else dieu_node.line_start
            child_page = khoan_node.lines[0].page if khoan_node.lines else dieu_node.page_start
            child_char_start = khoan_node.lines[0].char_start if khoan_node.lines else dieu_node.char_start

            child = LegalChunk(
                chunk_id=child_id,
                doc_id=doc_meta["doc_id"],
                chunk_level="child",
                parent_id=parent_id,
                text=khoan_node.full_text,
                original_text=khoan_node.full_text,
                page_number=child_page,
                line_start=child_line_start,
                line_end=khoan_node.line_end,
                char_start=child_char_start,
                char_end=khoan_node.char_end,
                doc_number=doc_meta["doc_number"],
                doc_type=doc_meta["doc_type"],
                issuer=doc_meta["issuer"],
                issue_date=doc_meta["issue_date"],
                effective_date=doc_meta.get("effective_date", ""),
                article=dieu_node.label,
                clause=khoan_node.label,
                point=None,
            )
            child_chunks.append(child)

    return parent_chunks, child_chunks


def _make_id(doc_id: str, *labels: str) -> str:
    raw = f"{doc_id}__{'__'.join(labels)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]
