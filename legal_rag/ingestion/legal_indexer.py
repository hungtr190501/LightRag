"""LegalDocumentIndexer — điều phối toàn bộ pipeline ingestion.

Kết hợp:
  1. Chunking pipeline (Qdrant) — semantic retrieval
  2. LightRAG insert (entity/relation extraction → KG)
  3. Legal graph builder (Neo4j) — inter-document relations
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from lightrag import LightRAG
    from legal_rag.storage.qdrant_storage import QdrantLegalVectorStorage
    from legal_rag.graph.builder import LegalGraphBuilder

logger = logging.getLogger(__name__)


class LegalDocumentIndexer:
    """Facade cho toàn bộ pipeline ingestion."""

    def __init__(
        self,
        rag: "LightRAG",
        qdrant: "QdrantLegalVectorStorage",
        graph_builder: Optional["LegalGraphBuilder"] = None,
        enable_contextual: bool = True,
        enable_graph: bool = True,
        use_llm_relations: bool = False,
        use_ocr: bool = False,
    ):
        self.rag = rag
        self.qdrant = qdrant
        self.graph_builder = graph_builder
        self.enable_contextual = enable_contextual
        self.enable_graph = enable_graph
        self.use_llm_relations = use_llm_relations
        self.use_ocr = use_ocr

    async def ingest_pdf(
        self,
        pdf_path: str,
        doc_meta: dict,
    ) -> dict:
        """Ingest một file (PDF hoặc ảnh) vào toàn bộ hệ thống.

        doc_meta cần có: doc_id, doc_number, doc_type, issuer, issue_date
        Optional: effective_date, title, legal_domain, status

        Returns: {qdrant_chunks, lightrag_status, graph_relations}
        """
        if "doc_id" not in doc_meta:
            doc_meta["doc_id"] = _make_doc_id(pdf_path)

        result: dict = {"pdf_path": pdf_path, "doc_id": doc_meta["doc_id"]}

        # ── 1. Qdrant: chunking + embedding ──────────────────────────────
        from legal_rag.chunking.pipeline import ingest_document
        try:
            chunk_result = await ingest_document(
                file_path=pdf_path,
                doc_meta=doc_meta,
                qdrant=self.qdrant,
                enable_contextual=self.enable_contextual,
                use_ocr=self.use_ocr,
            )
            result["qdrant_chunks"] = chunk_result
            logger.info("Qdrant ingestion done: %s", chunk_result)
        except Exception as e:
            logger.error("Qdrant ingestion failed for %s: %s", pdf_path, e)
            result["qdrant_error"] = str(e)

        # ── 2. LightRAG: entity/relation extraction ───────────────────────
        full_text = ""
        try:
            full_text = await _extract_full_text(pdf_path, use_ocr=self.use_ocr)
            await self.rag.ainsert(
                full_text,
                ids=[doc_meta["doc_id"]],
                file_paths=[pdf_path],
            )
            # ainsert không raise khi LLM extraction fail nội bộ — check doc_status
            doc_status_obj = await self.rag.doc_status.get_by_id(doc_meta["doc_id"])
            if doc_status_obj is not None:
                status_val = getattr(doc_status_obj, "status", None)
                status_str = status_val.value if hasattr(status_val, "value") else str(status_val)
                result["lightrag_status"] = status_str
                if status_str == "failed":
                    err_detail = getattr(doc_status_obj, "error", "") or "LightRAG entity extraction failed (xem server log)"
                    result["lightrag_error"] = err_detail
                    logger.error("LightRAG FAILED for %s: %s", doc_meta["doc_number"], err_detail)
                else:
                    logger.info("LightRAG status for %s: %s", doc_meta["doc_number"], status_str)
            else:
                result["lightrag_status"] = "processed"
                logger.info("LightRAG insertion done for %s", doc_meta["doc_number"])
        except Exception as e:
            logger.error("LightRAG insertion failed: %s", e)
            result["lightrag_error"] = str(e)

        # ── 3. Neo4j: inter-document relations ───────────────────────────
        if self.enable_graph and self.graph_builder:
            try:
                text_for_graph = (
                    full_text
                    if "full_text" in result or full_text  # type: ignore[truthy-bool]
                    else await _extract_full_text(pdf_path, use_ocr=self.use_ocr)
                )
                n_relations = await self.graph_builder.add_document(
                    doc_meta=doc_meta,
                    full_text=text_for_graph,
                    use_llm=self.use_llm_relations,
                )
                result["graph_relations"] = n_relations
            except Exception as e:
                logger.error("Graph build failed: %s", e)
                result["graph_error"] = str(e)

        return result

    async def ingest_text(
        self,
        text: str,
        doc_meta: dict,
    ) -> dict:
        """Ingest raw text (không có file PDF)."""
        if "doc_id" not in doc_meta:
            doc_meta["doc_id"] = hashlib.sha256(text[:200].encode()).hexdigest()[:16]

        result: dict = {"doc_id": doc_meta["doc_id"]}

        try:
            await self.rag.ainsert(
                text,
                ids=[doc_meta["doc_id"]],
            )
            result["lightrag_status"] = "queued"
        except Exception as e:
            result["lightrag_error"] = str(e)

        if self.enable_graph and self.graph_builder:
            try:
                n_relations = await self.graph_builder.add_document(
                    doc_meta=doc_meta,
                    full_text=text,
                    use_llm=self.use_llm_relations,
                )
                result["graph_relations"] = n_relations
            except Exception as e:
                result["graph_error"] = str(e)

        return result


def _make_doc_id(file_path: str) -> str:
    basename = os.path.basename(file_path)
    return hashlib.sha256(basename.encode()).hexdigest()[:16]


async def _extract_full_text(file_path: str, use_ocr: bool = False) -> str:
    """Trích xuất toàn bộ text từ file (dùng cho LightRAG + graph)."""
    from legal_rag.chunking.ocr_client import (
        IMAGE_EXTENSIONS, extract_image, extract_pdf_with_ocr, is_text_sparse,
    )
    from legal_rag.chunking.pipeline import DOCX_EXTENSIONS, MD_EXTENSIONS, TEXT_EXTENSIONS
    from pathlib import Path

    ext = Path(file_path).suffix.lower()

    # Image → OCR
    if ext in IMAGE_EXTENSIONS:
        lines, _ = await extract_image(file_path)
        return "\n".join(ln["text"] for ln in lines)

    # DOCX
    if ext in DOCX_EXTENSIONS:
        try:
            from docx import Document  # type: ignore
            doc = Document(file_path)
            return "\n".join(p.text for p in doc.paragraphs)
        except Exception as e:
            logger.warning("python-docx failed: %s", e)
            return ""

    # Markdown / Text
    if ext in MD_EXTENSIONS or ext in TEXT_EXTENSIONS:
        with open(file_path, encoding="utf-8", errors="replace") as f:
            return f.read()

    # PDF via OCR (explicit)
    if use_ocr:
        lines, _ = await extract_pdf_with_ocr(file_path)
        return "\n".join(ln["text"] for ln in lines)

    # PDF via pdfplumber
    text = ""
    try:
        import pdfplumber  # type: ignore
        with pdfplumber.open(file_path) as pdf:
            text = "\n".join(
                page.extract_text(layout=True) or "" for page in pdf.pages
            )
    except Exception as e:
        logger.warning("pdfplumber failed: %s", e)

    # Auto-detect sparse → OCR fallback
    if not text.strip() or len(text) < 200:
        logger.info("Text too sparse, using OCR fallback for %s", file_path)
        lines, _ = await extract_pdf_with_ocr(file_path)
        return "\n".join(ln["text"] for ln in lines)

    return text
