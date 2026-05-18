"""Trích xuất quan hệ pháp lý giữa các văn bản.

Kết hợp:
  1. Regex-based (nhanh, chính xác, confidence cao)
  2. LLM-based via vLLM (linh hoạt, xử lý câu phức tạp)
"""
from __future__ import annotations

import json
import re
from typing import Optional

from legal_rag.graph.legal_relations import RELATION_KEYWORDS, LegalRelationType

# Pattern nhận dạng số hiệu văn bản pháp luật Việt Nam
_DOC_NUMBER_PATTERNS = [
    r"\d{1,3}/\d{4}/(?:NĐ|TT|QĐ|CT|NQ|PL|NQLT)-[A-ZĐẦẮẰẶẤẦẨẪẬẮẰẶẺẼẸẾỀỂỄỆỈĨỊỌỐỒỔỖỘỞỜỠỢỤỨỪỬỮỰỲỶỸỴ]+",
    r"\d{1,3}/\d{4}/[A-ZĐẦẮẰẶẤẦẨẪẬẮẰẶ-]{3,}",
    r"[Ll]uật\s+[A-ZĐÁÀẢÃẠĂẮẰẲẴẶÂẤẦẨẪẬ][^\n,;.]{5,60}(?:\s+\d{4})",
    r"[Nn]ghị\s+quyết\s+số\s+\d+[^\n,;.]{0,40}",
    r"[Pp]háp\s+lệnh\s+[A-ZĐ][^\n,;.]{5,50}(?:\s+\d{4})",
]
_DOC_PATTERN = re.compile(
    "|".join(f"({p})" for p in _DOC_NUMBER_PATTERNS),
    re.IGNORECASE | re.UNICODE,
)


class LegalRelationExtractor:
    """Trích xuất quan hệ pháp lý từ text."""

    def extract_from_text(
        self,
        text: str,
        source_doc_number: str,
    ) -> list[dict]:
        """Regex-based extraction — nhanh, dùng cho bulk import.

        Returns list of:
            {source, relation, target, context, confidence}
        """
        relations: list[dict] = []
        for sentence in self._split_sentences(text):
            targets = self._find_doc_numbers(sentence)
            if not targets:
                continue
            rel_type = self._classify_relation(sentence)
            if rel_type is None:
                continue
            for target in targets:
                target = target.strip()
                if target and target != source_doc_number:
                    relations.append({
                        "source": source_doc_number,
                        "relation": rel_type.value,
                        "target": target,
                        "context": sentence[:200],
                        "confidence": 0.88,
                        "method": "regex",
                    })
        return relations

    async def extract_from_text_llm(
        self,
        text: str,
        source_doc_number: str,
    ) -> list[dict]:
        """LLM-based extraction — chính xác hơn cho câu phức tạp."""
        from legal_rag.llm.vllm_adapter import vllm_complete

        prompt = _LLM_PROMPT.format(
            source_doc=source_doc_number,
            text=text[:2000],
            relation_types=", ".join(r.value for r in LegalRelationType),
        )
        raw = await vllm_complete(
            prompt=prompt,
            max_tokens=512,
            temperature=0.05,
        )
        return self._parse_llm_output(raw, source_doc_number)

    # ── private ─────────────────────────────────────────────────────────

    def _classify_relation(self, sentence: str) -> Optional[LegalRelationType]:
        lower = sentence.lower()
        for rel_type, keywords in RELATION_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                return rel_type
        return None

    def _find_doc_numbers(self, sentence: str) -> list[str]:
        matches = _DOC_PATTERN.findall(sentence)
        return [m for group in matches for m in group if m]

    def _split_sentences(self, text: str) -> list[str]:
        return re.split(r"(?<=[.;])\s+|\n", text)

    def _parse_llm_output(self, raw: str, source: str) -> list[dict]:
        try:
            # Find JSON in response
            json_match = re.search(r"\{[\s\S]*\}", raw)
            if not json_match:
                return []
            data = json.loads(json_match.group())
            relations = []
            for r in data.get("relations", []):
                if r.get("source") and r.get("target") and r.get("relation"):
                    relations.append({
                        "source": r["source"],
                        "relation": r["relation"],
                        "target": r["target"],
                        "context": r.get("description", ""),
                        "confidence": float(r.get("confidence", 0.8)),
                        "method": "llm",
                    })
            return relations
        except (json.JSONDecodeError, KeyError, ValueError):
            return []


_LLM_PROMPT = """\
Hãy trích xuất TẤT CẢ quan hệ pháp lý giữa các văn bản trong đoạn text sau.

VĂN BẢN NGUỒN: {source_doc}

ĐOẠN VĂN BẢN:
{text}

Trả về JSON:
{{
  "relations": [
    {{
      "source": "số hiệu văn bản nguồn",
      "relation": "loại quan hệ",
      "target": "số hiệu văn bản đích",
      "target_article": "Điều X (nếu đề cập điều cụ thể, để trống nếu không)",
      "description": "mô tả ngắn",
      "confidence": 0.0-1.0
    }}
  ]
}}

Các loại quan hệ hợp lệ: {relation_types}

CHỈ trả về JSON thuần túy, không giải thích thêm."""
