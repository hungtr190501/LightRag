"""OCR Client — PaddleOCR-VL REST API adapter.

Gọi OCR server tại OCR_HOST (mặc định http://192.168.2.182:7800).
Hỗ trợ:
  - Image files:  PNG, JPG, JPEG, TIFF, BMP, WEBP
  - PDF (scanned): tự split theo trang, gọi OCR từng trang

Trả về list[dict] cùng format với _extract_lines() trong pipeline.py:
  {"text": str, "page": int, "global_line": int, "char_start": int, "char_end": int}
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

_DEFAULT_OCR_HOST = "http://192.168.2.182:7800"
_EXTRACT_ENDPOINT = "/api/v1/extract"
_TIMEOUT_SECONDS = 120  # OCR có thể chậm với file lớn

# File types mà OCR server chấp nhận (không phải pdfplumber)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}


def get_ocr_host() -> str:
    return os.getenv("OCR_HOST", _DEFAULT_OCR_HOST).rstrip("/")


def is_image_file(file_path: str) -> bool:
    return Path(file_path).suffix.lower() in IMAGE_EXTENSIONS


# ── Core API call ────────────────────────────────────────────────────


async def _call_ocr_api(file_path: str) -> str:
    """Upload file → gọi OCR API → trả về nội dung markdown.

    Args:
        file_path: đường dẫn file (image hoặc PDF single-page)

    Returns:
        Nội dung text đã OCR (markdown format)

    Raises:
        RuntimeError nếu API lỗi hoặc không có markdown URL
    """
    host = get_ocr_host()
    url = f"{host}{_EXTRACT_ENDPOINT}"

    timeout = aiohttp.ClientTimeout(total=_TIMEOUT_SECONDS)
    file_name = Path(file_path).name

    async with aiohttp.ClientSession(timeout=timeout) as session:
        with open(file_path, "rb") as f:
            data = aiohttp.FormData()
            # Detect MIME type from extension
            ext = Path(file_path).suffix.lower()
            mime_map = {
                ".pdf": "application/pdf",
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".tiff": "image/tiff",
                ".tif": "image/tiff",
                ".bmp": "image/bmp",
                ".webp": "image/webp",
            }
            mime = mime_map.get(ext, "application/octet-stream")
            data.add_field("file", f, filename=file_name, content_type=mime)

            async with session.post(url, data=data) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise RuntimeError(
                        f"OCR API returned HTTP {resp.status}: {body[:200]}"
                    )
                result = await resp.json()

    if result.get("status") != "success":
        raise RuntimeError(f"OCR API error: {result}")

    markdown_url = (result.get("download_urls") or {}).get("markdown")
    if not markdown_url:
        raise RuntimeError(f"OCR API returned no markdown URL: {result}")

    # Download markdown content
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(markdown_url) as resp:
            if resp.status != 200:
                raise RuntimeError(
                    f"Failed to download OCR markdown (HTTP {resp.status}): {markdown_url}"
                )
            markdown_text = await resp.text(encoding="utf-8")

    logger.debug(
        "OCR: %s → %d chars (%.1fs, %d pages, engine=%s)",
        file_name,
        len(markdown_text),
        result.get("processing_time_seconds", 0),
        result.get("total_pages", 1),
        result.get("ocr_engine", "?"),
    )
    return markdown_text


# ── Markdown → lines ─────────────────────────────────────────────────


def _markdown_to_lines(
    markdown_text: str,
    page_offset: int = 1,
    global_line_offset: int = 0,
    global_char_offset: int = 0,
) -> list[dict]:
    """Chuyển markdown text → list[dict] theo format pipeline.

    Tự phát hiện page markers:
      - `\f` (form feed — PDF-to-text standard)
      - `---` hoặc `***` trên dòng riêng (markdown hr)
      - `<!-- page N -->` hoặc `[Page N]`
    """
    # Split theo page markers trước
    page_texts = _split_pages(markdown_text)

    lines: list[dict] = []
    g_line = global_line_offset
    g_char = global_char_offset

    for page_idx, page_text in enumerate(page_texts):
        page_num = page_offset + page_idx
        for raw_line in page_text.split("\n"):
            # Bỏ qua separator lines từ markdown hr
            if re.fullmatch(r"[-*_]{3,}", raw_line.strip()):
                continue
            lines.append({
                "text": raw_line,
                "page": page_num,
                "global_line": g_line + 1,
                "char_start": g_char,
                "char_end": g_char + len(raw_line),
            })
            g_line += 1
            g_char += len(raw_line) + 1  # +1 for newline

    return lines


def _split_pages(text: str) -> list[str]:
    """Tách text thành list[str] theo page markers."""
    # Form feed (most reliable for PDF extraction)
    if "\f" in text:
        return text.split("\f")

    # HTML-style page comment: <!-- page 2 --> or <!-- Page 2 -->
    html_split = re.split(r"<!--\s*[Pp]age\s+\d+\s*-->", text)
    if len(html_split) > 1:
        return html_split

    # Bracket style: [Page 2] or [page 2]
    bracket_split = re.split(r"\[\s*[Pp]age\s+\d+\s*\]", text)
    if len(bracket_split) > 1:
        return bracket_split

    # Horizontal rule on its own line (used by some OCR tools)
    hr_split = re.split(r"\n[-*_]{3,}\n", text)
    if len(hr_split) > 1:
        return hr_split

    # No page markers → treat as single page
    return [text]


# ── High-level extraction functions ──────────────────────────────────


async def extract_image(file_path: str) -> tuple[list[dict], str]:
    """OCR một file ảnh.

    Returns:
        (lines, doc_header) — cùng format với _extract_lines() trong pipeline
    """
    logger.info("OCR image: %s", file_path)
    markdown = await _call_ocr_api(file_path)
    lines = _markdown_to_lines(markdown, page_offset=1)
    doc_header = "\n".join(ln["text"] for ln in lines[:40])
    return lines, doc_header


async def extract_pdf_with_ocr(
    pdf_path: str,
    max_concurrent_pages: int = 4,
) -> tuple[list[dict], str]:
    """OCR một file PDF bằng cách split từng trang thành ảnh → gọi OCR API.

    Dùng khi pdfplumber trả về ít text (PDF scan/ảnh).
    Mỗi trang PDF được render thành PNG rồi gửi lên OCR API.

    Returns:
        (lines, doc_header)
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as e:
        raise ImportError(
            "PyMuPDF required for OCR on scanned PDFs: pip install pymupdf"
        ) from e

    doc = fitz.open(pdf_path)
    total_pages = len(doc)
    logger.info("OCR scanned PDF: %s (%d pages)", pdf_path, total_pages)

    semaphore = asyncio.Semaphore(max_concurrent_pages)

    async def _ocr_page(page_num: int, page_idx: int) -> list[dict]:
        async with semaphore:
            page = doc[page_idx]
            # Render page → PNG in memory (300 DPI for good OCR quality)
            mat = fitz.Matrix(300 / 72, 300 / 72)
            pix = page.get_pixmap(matrix=mat)

            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                tmp_path = tmp.name
                pix.save(tmp_path)

            try:
                markdown = await _call_ocr_api(tmp_path)
            finally:
                os.unlink(tmp_path)

            return _markdown_to_lines(markdown, page_offset=page_num)

    # Run pages concurrently (respecting semaphore)
    tasks = [_ocr_page(i + 1, i) for i in range(total_pages)]
    page_results = await asyncio.gather(*tasks, return_exceptions=True)

    # Merge all pages into one list, renumber global_line / char
    all_lines: list[dict] = []
    g_line = 0
    g_char = 0
    for page_idx, result in enumerate(page_results):
        if isinstance(result, Exception):
            logger.error("OCR failed for page %d: %s", page_idx + 1, result)
            continue
        for ln in result:
            all_lines.append({
                **ln,
                "global_line": g_line + 1,
                "char_start": g_char,
                "char_end": g_char + len(ln["text"]),
            })
            g_line += 1
            g_char += len(ln["text"]) + 1

    doc.close()
    doc_header = "\n".join(ln["text"] for ln in all_lines if ln["page"] == 1)[:2000]
    logger.info("OCR PDF complete: %d lines from %d pages", len(all_lines), total_pages)
    return all_lines, doc_header


# ── Density check (auto-detect scanned PDF) ──────────────────────────


def is_text_sparse(lines: list[dict], min_chars_per_page: int = 100) -> bool:
    """Kiểm tra xem PDF có bị scan (thiếu text) không.

    Trả về True nếu trung bình mỗi trang < min_chars_per_page ký tự.
    """
    if not lines:
        return True
    pages = {ln["page"] for ln in lines}
    total_chars = sum(len(ln["text"]) for ln in lines)
    avg = total_chars / len(pages) if pages else 0
    return avg < min_chars_per_page
