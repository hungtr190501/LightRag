"""Pipeline hoàn chỉnh: PDF/Image → indexed in Qdrant.

5 tầng:
  1. Text extraction (pdfplumber hoặc OCR API)
  2. Structure-aware split (Điều/Khoản/Điểm) + Multi-granularity chunks
  3. Contextual headers (vLLM batch)
  4. BGE-M3 embed (dense + sparse)
  5. Upsert Qdrant

OCR auto-detection:
  - Image files (.png/.jpg/...) → luôn dùng OCR API
  - PDF với text thưa (< 100 chars/page avg) → fallback OCR
  - use_ocr=True → ép dùng OCR bất kể loại file
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from legal_rag.chunking.ocr_client import (
    IMAGE_EXTENSIONS,
    extract_image,
    extract_pdf_with_ocr,
    is_text_sparse,
)

if TYPE_CHECKING:
    from legal_rag.storage.qdrant_storage import QdrantLegalVectorStorage

logger = logging.getLogger(__name__)

_MIN_CHARS_PER_PAGE = 100  # ngưỡng auto-detect PDF scan


async def ingest_document(
    file_path: str,
    doc_meta: dict,
    qdrant: "QdrantLegalVectorStorage",
    enable_contextual: bool = True,
    use_ocr: bool = False,
) -> dict:
    """Pipeline hoàn chỉnh ingest một file vào Qdrant.

    Args:
        file_path: đường dẫn file (PDF hoặc ảnh PNG/JPG/...)
        doc_meta: dict với keys: doc_id, doc_number, doc_type, issuer,
                  issue_date, effective_date (optional)
        qdrant: QdrantLegalVectorStorage instance
        enable_contextual: chạy contextual header generation (vLLM)
        use_ocr: ép dùng OCR API — bỏ qua pdfplumber

    Returns:
        {parent_count, child_count, total_chunks, extraction_method}
    """
    from legal_rag.chunking.structure_splitter import StructureAwareSplitter
    from legal_rag.chunking.multigranularity import build_parent_child_chunks
    from legal_rag.chunking.contextual_generator import add_contextual_headers
    from legal_rag.chunking.embedder import get_embedder
    from pathlib import Path

    # ── Tầng 1: Text extraction ─────────────────────────────────────────
    all_lines, doc_header, extraction_method = await _extract_lines(
        file_path, use_ocr=use_ocr
    )
    logger.info(
        "Extracted %d lines from %s (method=%s)",
        len(all_lines), file_path, extraction_method,
    )

    # ── Tầng 2: Parse structure → parent+child chunks ───────────────────
    splitter = StructureAwareSplitter()
    dieu_nodes = splitter.parse(all_lines)
    logger.info("Found %d Điều nodes", len(dieu_nodes))

    parent_chunks, child_chunks = build_parent_child_chunks(dieu_nodes, doc_meta)
    all_chunks = parent_chunks + child_chunks
    logger.info("Built %d parent + %d child chunks", len(parent_chunks), len(child_chunks))

    # ── Tầng 3: Contextual headers (vLLM) ──────────────────────────────
    if enable_contextual and all_chunks:
        logger.info("Generating contextual headers for %d chunks...", len(all_chunks))
        all_chunks = await add_contextual_headers(all_chunks, doc_header, doc_meta)

    # ── Tầng 4: Embed (BGE-M3) ─────────────────────────────────────────
    embedder = get_embedder()
    logger.info("Embedding %d chunks with BGE-M3...", len(all_chunks))
    embedded = embedder.embed_chunks(all_chunks, batch_size=32)

    # ── Tầng 5: Upsert Qdrant ──────────────────────────────────────────
    await qdrant.upsert_legal_chunks(embedded)
    logger.info("Upserted %d chunks to Qdrant", len(embedded))

    return {
        "parent_count": len(parent_chunks),
        "child_count": len(child_chunks),
        "total_chunks": len(all_chunks),
        "extraction_method": extraction_method,
    }


DOCX_EXTENSIONS = {".docx"}
MD_EXTENSIONS = {".md", ".markdown"}
TEXT_EXTENSIONS = {".txt"}
ALL_SUPPORTED_EXTENSIONS = (
    {".pdf"}
    | IMAGE_EXTENSIONS
    | DOCX_EXTENSIONS
    | MD_EXTENSIONS
    | TEXT_EXTENSIONS
)


async def _extract_lines(
    file_path: str,
    use_ocr: bool = False,
) -> tuple[list[dict], str, str]:
    """Trích xuất lines từ file, tự chọn phương pháp phù hợp.

    Returns:
        (lines, doc_header, method_name)
        method_name: "pdfplumber" | "ocr_image" | "ocr_pdf" | "docx" | "markdown" | "text"
    """
    from pathlib import Path
    ext = Path(file_path).suffix.lower()

    # 1. File ảnh → OCR
    if ext in IMAGE_EXTENSIONS:
        lines, header = await extract_image(file_path)
        return lines, header, "ocr_image"

    # 2. DOCX
    if ext in DOCX_EXTENSIONS:
        lines, header = _extract_lines_docx(file_path)
        return lines, header, "docx"

    # 3. Markdown / Text
    if ext in MD_EXTENSIONS or ext in TEXT_EXTENSIONS:
        lines, header = _extract_lines_text(file_path)
        return lines, header, "markdown" if ext in MD_EXTENSIONS else "text"

    # 4. Ép OCR cho PDF
    if use_ocr:
        lines, header = await extract_pdf_with_ocr(file_path)
        return lines, header, "ocr_pdf"

    # 5. Thử pdfplumber trước cho PDF
    lines, header = _extract_lines_pdfplumber(file_path)

    # 6. Auto-detect: nếu text thưa → fallback OCR
    if is_text_sparse(lines, min_chars_per_page=_MIN_CHARS_PER_PAGE):
        logger.info(
            "PDF appears to be scanned (sparse text). Switching to OCR: %s", file_path
        )
        lines, header = await extract_pdf_with_ocr(file_path)
        return lines, header, "ocr_pdf"

    return lines, header, "pdfplumber"


def _extract_lines_docx(docx_path: str) -> tuple[list[dict], str]:
    """Trích xuất lines từ file DOCX bằng python-docx."""
    try:
        from docx import Document  # type: ignore
    except ImportError as e:
        raise ImportError("python-docx required: pip install python-docx") from e

    doc = Document(docx_path)
    all_lines: list[dict] = []
    global_line = 0
    global_char = 0

    for para in doc.paragraphs:
        text = para.text
        all_lines.append({
            "text": text,
            "page": 1,
            "global_line": global_line + 1,
            "char_start": global_char,
            "char_end": global_char + len(text),
        })
        global_line += 1
        global_char += len(text) + 1

    doc_header = "\n".join(ln["text"] for ln in all_lines[:40])
    return all_lines, doc_header


def _extract_lines_text(file_path: str) -> tuple[list[dict], str]:
    """Trích xuất lines từ file text/markdown."""
    with open(file_path, encoding="utf-8", errors="replace") as f:
        raw = f.read()

    all_lines: list[dict] = []
    global_char = 0
    for i, line in enumerate(raw.split("\n"), start=1):
        all_lines.append({
            "text": line,
            "page": 1,
            "global_line": i,
            "char_start": global_char,
            "char_end": global_char + len(line),
        })
        global_char += len(line) + 1

    doc_header = "\n".join(ln["text"] for ln in all_lines[:40])
    return all_lines, doc_header


def _extract_lines_pdfplumber(pdf_path: str) -> tuple[list[dict], str]:
    """Trích xuất lines từ PDF text-based bằng pdfplumber."""
    try:
        import pdfplumber  # type: ignore
    except ImportError as e:
        raise ImportError("pdfplumber required: pip install pdfplumber") from e

    all_lines: list[dict] = []
    global_line = 0
    global_char = 0

    with pdfplumber.open(pdf_path) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            text = page.extract_text(layout=True) or ""
            for line in text.split("\n"):
                all_lines.append({
                    "text": line,
                    "page": page_num,
                    "global_line": global_line + 1,
                    "char_start": global_char,
                    "char_end": global_char + len(line),
                })
                global_line += 1
                global_char += len(line) + 1

    first_page_lines = [ln["text"] for ln in all_lines if ln["page"] == 1]
    doc_header = "\n".join(first_page_lines[:40])
    return all_lines, doc_header
