"""LegalGraphBuilder — xây dựng Knowledge Graph pháp lý trong Neo4j.

Tự động extract và lưu quan hệ khi import văn bản.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from neo4j import AsyncGraphDatabase  # type: ignore
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False


class LegalGraphBuilder:
    """Xây dựng Knowledge Graph pháp lý tự động khi import văn bản."""

    def __init__(
        self,
        uri: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
    ):
        if not HAS_NEO4J:
            raise ImportError("neo4j required: pip install neo4j")

        self._uri = uri or os.getenv("NEO4J_URI", "bolt://localhost:7687")
        self._user = user or os.getenv("NEO4J_USERNAME", "neo4j")
        self._password = password or os.getenv("NEO4J_PASSWORD", "legalrag2024")
        self._driver = AsyncGraphDatabase.driver(
            self._uri, auth=(self._user, self._password)
        )
        from legal_rag.graph.relation_extractor import LegalRelationExtractor
        self._extractor = LegalRelationExtractor()

    async def close(self):
        await self._driver.close()

    async def ensure_schema(self):
        """Tạo constraints + indexes nếu chưa có."""
        async with self._driver.session() as session:
            await session.run(
                "CREATE CONSTRAINT doc_number_unique IF NOT EXISTS "
                "FOR (d:Document) REQUIRE d.doc_number IS UNIQUE"
            )
            await session.run(
                "CREATE INDEX doc_status IF NOT EXISTS "
                "FOR (d:Document) ON (d.status)"
            )
            await session.run(
                "CREATE INDEX doc_domain IF NOT EXISTS "
                "FOR (d:Document) ON (d.legal_domain)"
            )

    async def add_document(
        self,
        doc_meta: dict,
        full_text: str,
        use_llm: bool = False,
    ) -> int:
        """Pipeline khi import một văn bản mới.

        Returns: số quan hệ đã tạo.
        """
        await self._upsert_document_node(doc_meta)

        # Regex extraction (luôn chạy)
        regex_rels = self._extractor.extract_from_text(
            full_text, doc_meta["doc_number"]
        )

        # LLM extraction cho 3000 ký tự đầu (thường có nhiều tham chiếu nhất)
        llm_rels = []
        if use_llm:
            try:
                llm_rels = await self._extractor.extract_from_text_llm(
                    full_text[:3000], doc_meta["doc_number"]
                )
            except Exception as e:
                logger.warning("LLM relation extraction failed: %s", e)

        all_rels = _deduplicate(regex_rels + llm_rels)

        for rel in all_rels:
            await self._upsert_relation(rel)

        logger.info(
            "Graph: %s → %d relations (regex=%d, llm=%d)",
            doc_meta["doc_number"],
            len(all_rels),
            len(regex_rels),
            len(llm_rels),
        )
        return len(all_rels)

    async def get_related_documents(
        self,
        doc_number: str,
        max_depth: int = 1,
        max_neighbors: int = 10,
        status_filter: str = "HIEU_LUC",
    ) -> list[dict]:
        """Traverse graph để tìm văn bản liên quan.

        Args:
            doc_number: Số hiệu văn bản gốc
            max_depth: Độ sâu traversal tối đa (default 1, cap 5)
            max_neighbors: Số lượng văn bản liên quan tối đa (default 10, cap 50)
            status_filter: Lọc theo trạng thái hiệu lực
        """
        # Enforce caps to prevent graph explosion (Problem 8)
        max_depth = min(max_depth, 5)
        max_neighbors = min(max_neighbors, 50)

        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (d:Document {doc_number: $doc_number})-[r]-(related:Document)
                WHERE $status_filter = '' OR related.status = $status_filter
                RETURN related.doc_number AS doc_number,
                       related.doc_type  AS doc_type,
                       related.title     AS title,
                       related.status    AS status,
                       type(r)           AS relation_type
                LIMIT $max_neighbors
                """,
                doc_number=doc_number,
                status_filter=status_filter,
                max_neighbors=max_neighbors,
            )
            return [dict(record) async for record in result]

    async def get_document_history(self, doc_number: str) -> list[dict]:
        """Lịch sử sửa đổi / thay thế của một văn bản."""
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH path = (current:Document)-[:SUA_DOI|BAI_BO|THAY_THE*]->(original:Document)
                WHERE original.doc_number = $doc_number
                RETURN [n IN nodes(path) | n.doc_number] AS chain,
                       [r IN relationships(path) | type(r)] AS rel_chain
                LIMIT 20
                """,
                doc_number=doc_number,
            )
            return [dict(record) async for record in result]

    async def find_documents_by_domain(
        self, domain: str, status: str = "HIEU_LUC"
    ) -> list[dict]:
        """Tìm văn bản theo lĩnh vực pháp lý."""
        async with self._driver.session() as session:
            result = await session.run(
                """
                MATCH (d:Document)
                WHERE any(dom IN d.legal_domain WHERE dom CONTAINS $domain)
                  AND ($status = '' OR d.status = $status)
                RETURN d.doc_number AS doc_number,
                       d.doc_type   AS doc_type,
                       d.title      AS title,
                       d.issue_date AS issue_date,
                       d.status     AS status
                ORDER BY d.issue_date DESC
                LIMIT 50
                """,
                domain=domain,
                status=status,
            )
            return [dict(record) async for record in result]

    # ── private ─────────────────────────────────────────────────────────

    async def _upsert_document_node(self, meta: dict):
        async with self._driver.session() as session:
            await session.run(
                """
                MERGE (d:Document {doc_number: $doc_number})
                SET d.doc_type      = $doc_type,
                    d.title         = $title,
                    d.issuer        = $issuer,
                    d.issue_date    = $issue_date,
                    d.effective_date = $effective_date,
                    d.status        = $status,
                    d.legal_domain  = $legal_domain
                """,
                doc_number=meta["doc_number"],
                doc_type=meta.get("doc_type", "Văn bản"),
                title=meta.get("title", ""),
                issuer=meta.get("issuer", ""),
                issue_date=meta.get("issue_date", ""),
                effective_date=meta.get("effective_date", ""),
                status=meta.get("status", "HIEU_LUC"),
                legal_domain=meta.get("legal_domain", []),
            )

    async def _upsert_relation(self, rel: dict):
        """Tạo edge, tự động tạo node target nếu chưa có."""
        relation_type = rel["relation"]
        async with self._driver.session() as session:
            await session.run(
                f"""
                MERGE (source:Document {{doc_number: $source}})
                MERGE (target:Document {{doc_number: $target}})
                MERGE (source)-[r:{relation_type}]->(target)
                SET r.context      = $context,
                    r.confidence   = $confidence,
                    r.method       = $method,
                    r.extracted_at = datetime()
                """,
                source=rel["source"],
                target=rel["target"],
                context=rel.get("context", ""),
                confidence=rel.get("confidence", 0.8),
                method=rel.get("method", "regex"),
            )


def _deduplicate(relations: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    unique: list[dict] = []
    for r in relations:
        key = (r["source"], r["relation"], r["target"])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique
