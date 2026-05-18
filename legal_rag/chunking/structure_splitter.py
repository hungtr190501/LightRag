"""Tầng 1 — Structure-aware Splitter.

Đọc toàn bộ document → xây cây cấu trúc pháp lý Điều/Khoản/Điểm.
Nguyên tắc: KHÔNG BAO GIỜ cắt bên trong một Điều.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ──────────────────────────────────────────────
# Regex nhận dạng ranh giới cấu trúc pháp lý VN
# Thứ tự: pattern, boundary_type, level (thấp = cao hơn trong cây)
# ──────────────────────────────────────────────
_BOUNDARY_PATTERNS: list[tuple[str, str, int]] = [
    (r"^PHẦN\s+(?:THỨ\s+)?[IVXLCDM\d]+", "phan", 1),
    (r"^CHƯƠNG\s+[IVXLCDM\d]+", "chuong", 2),
    (r"^Mục\s+\d+", "muc", 3),
    # Điều — ranh giới cứng nhất
    (r"^(?:Đ|đ)iều\s+\d+[\.\:]?", "dieu", 4),
    # Khoản: bắt đầu bằng số + dấu chấm + chữ hoa hoặc số
    (r"^\d+\.\s+[A-ZĐẮẰẶẤẦẨẪẬẮẰẶẺẼẸẾỀỂỄỆỈĨỊỌỐỒỔỖỘỞỜỠỢỤỨỪỬỮỰỲỶỸỴ]", "khoan", 5),
    # Điểm: chữ thường + đóng ngoặc
    (r"^[a-zđ]\)\s", "diem", 6),
]

_COMPILED = [
    (re.compile(p, re.IGNORECASE | re.UNICODE), btype, lvl)
    for p, btype, lvl in _BOUNDARY_PATTERNS
]


@dataclass
class StructuredLine:
    text: str
    page: int
    global_line: int
    char_start: int
    char_end: int
    boundary_type: Optional[str] = None
    boundary_level: int = 99
    article_num: Optional[int] = None
    clause_num: Optional[int] = None
    point_char: Optional[str] = None


@dataclass
class LegalNode:
    """Đơn vị trong cây pháp lý (Điều / Khoản / Điểm / Chương)."""

    level: str            # 'dieu' | 'khoan' | 'diem' | 'chuong'
    label: str            # "Điều 5" | "Khoản 2" | "Điểm a"
    lines: list[StructuredLine] = field(default_factory=list)
    children: list["LegalNode"] = field(default_factory=list)
    parent: Optional["LegalNode"] = field(default=None, repr=False)

    # ── derived properties ──────────────────────────────────────────────

    @property
    def text(self) -> str:
        return "\n".join(ln.text for ln in self.lines)

    @property
    def full_text(self) -> str:
        """Toàn bộ text kể cả children — dùng cho parent chunk."""
        parts = [self.text]
        for child in self.children:
            parts.append(child.full_text)
        return "\n".join(p for p in parts if p)

    def _all_lines(self) -> list[StructuredLine]:
        acc = list(self.lines)
        for child in self.children:
            acc.extend(child._all_lines())
        return acc

    @property
    def page_start(self) -> int:
        return self.lines[0].page if self.lines else 0

    @property
    def line_start(self) -> int:
        return self.lines[0].global_line if self.lines else 0

    @property
    def line_end(self) -> int:
        all_lines = self._all_lines()
        return all_lines[-1].global_line if all_lines else 0

    @property
    def char_start(self) -> int:
        return self.lines[0].char_start if self.lines else 0

    @property
    def char_end(self) -> int:
        all_lines = self._all_lines()
        return all_lines[-1].char_end if all_lines else 0


class StructureAwareSplitter:
    """Bước 1: parse document lines → cây LegalNode cấp Điều."""

    def parse(self, lines: list[dict]) -> list[LegalNode]:
        """
        Args:
            lines: list of dicts {text, page, global_line, char_start, char_end}
        Returns:
            list of Điều-level LegalNode (mỗi node chứa Khoản/Điểm con)
        """
        structured = [self._classify_line(ln) for ln in lines]
        return self._build_tree(structured)

    # ── private helpers ──────────────────────────────────────────────────

    def _classify_line(self, line_dict: dict) -> StructuredLine:
        text = line_dict["text"]
        stripped = text.strip()
        sl = StructuredLine(
            text=text,
            page=line_dict["page"],
            global_line=line_dict["global_line"],
            char_start=line_dict["char_start"],
            char_end=line_dict["char_end"],
        )
        for pattern, btype, level in _COMPILED:
            if pattern.match(stripped):
                sl.boundary_type = btype
                sl.boundary_level = level
                if btype == "dieu":
                    m = re.search(r"\d+", stripped)
                    sl.article_num = int(m.group()) if m else None
                elif btype == "khoan":
                    m = re.match(r"^(\d+)\.", stripped)
                    sl.clause_num = int(m.group(1)) if m else None
                elif btype == "diem":
                    m = re.match(r"^([a-zđ])\)", stripped)
                    sl.point_char = m.group(1) if m else None
                break
        return sl

    def _build_tree(self, lines: list[StructuredLine]) -> list[LegalNode]:
        """Xây cây Điều → Khoản → Điểm."""
        dieu_nodes: list[LegalNode] = []
        current_dieu: Optional[LegalNode] = None
        current_khoan: Optional[LegalNode] = None

        def _flush_khoan():
            nonlocal current_khoan
            if current_khoan and current_dieu:
                current_dieu.children.append(current_khoan)
                current_khoan = None

        def _flush_dieu():
            _flush_khoan()
            if current_dieu:
                dieu_nodes.append(current_dieu)

        for sl in lines:
            if sl.boundary_type == "dieu":
                _flush_dieu()
                label = f"Điều {sl.article_num}" if sl.article_num else sl.text.strip()[:40]
                current_dieu = LegalNode(level="dieu", label=label)
                current_dieu.lines.append(sl)

            elif sl.boundary_type == "khoan" and current_dieu:
                _flush_khoan()
                label = f"Khoản {sl.clause_num}" if sl.clause_num else sl.text.strip()[:20]
                current_khoan = LegalNode(level="khoan", label=label, parent=current_dieu)
                current_khoan.lines.append(sl)

            elif sl.boundary_type == "diem" and current_khoan:
                label = f"Điểm {sl.point_char}" if sl.point_char else sl.text.strip()[:10]
                diem_node = LegalNode(level="diem", label=label, parent=current_khoan)
                diem_node.lines.append(sl)
                current_khoan.children.append(diem_node)

            else:
                # Dòng thường → gắn vào node hiện tại
                if current_khoan:
                    if current_khoan.children:
                        current_khoan.children[-1].lines.append(sl)
                    else:
                        current_khoan.lines.append(sl)
                elif current_dieu:
                    current_dieu.lines.append(sl)
                # else: preamble trước Điều 1 — bỏ qua

        _flush_dieu()
        return dieu_nodes
