"""QdrantLegalVectorStorage — extends LightRAG BaseVectorStorage.

Hybrid search: dense (semantic) + sparse (BM25 keyword).
Payload filtering: doc_type, issuer, effective_date, doc_numbers...
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from typing import Any, Optional, final

from lightrag.base import BaseVectorStorage
from lightrag.utils import logger

try:
    from qdrant_client import QdrantClient, models as qmodels  # type: ignore
    from qdrant_client.models import (  # type: ignore
        Distance,
        FieldCondition,
        Filter,
        MatchAny,
        MatchValue,
        PointStruct,
        Range,
        SparseIndexParams,
        SparseVector,
        SparseVectorParams,
        VectorParams,
    )
    HAS_QDRANT = True
except ImportError:
    HAS_QDRANT = False

# Tên collection mặc định — workspace prefix được thêm vào khi cần
_DEFAULT_COLLECTION = "legal_documents"

# Các field cần index payload để filter nhanh
_INDEX_FIELDS = [
    ("doc_type", "keyword"),
    ("issuer", "keyword"),
    ("doc_number", "keyword"),
    ("chunk_level", "keyword"),
    ("article", "keyword"),
    ("page_number", "integer"),
    ("status", "keyword"),           # HIEU_LUC | HET_HIEU_LUC | BI_THAY_THE | SAP_HIEU_LUC
    ("is_primary_source", "bool"),   # filter out FAQ/blog noise
]


@final
@dataclass
class QdrantLegalVectorStorage(BaseVectorStorage):
    """Vector storage for legal documents using Qdrant.

    Configured via global_config["vector_db_storage_cls_kwargs"]:
      - host (str, default "localhost")
      - port (int, default 6333)
      - collection_name (str, default "legal_documents")
      - prefer_grpc (bool, default False)
    """

    def __post_init__(self):
        self._validate_embedding_func()

        if not HAS_QDRANT:
            raise ImportError("qdrant-client required: pip install qdrant-client")

        kwargs = self.global_config.get("vector_db_storage_cls_kwargs", {})
        cosine_threshold = kwargs.get("cosine_better_than_threshold", 0.2)
        self.cosine_better_than_threshold = cosine_threshold

        host = kwargs.get("host") or os.getenv("QDRANT_HOST", "localhost")
        port = int(kwargs.get("port") or os.getenv("QDRANT_PORT", "6333"))
        prefer_grpc = kwargs.get("prefer_grpc", False)

        base_collection = kwargs.get("collection_name", _DEFAULT_COLLECTION)
        # Workspace isolation: prefix collection name
        if self.workspace:
            self._collection = f"{self.workspace}_{base_collection}"
        else:
            self._collection = base_collection

        self._client = QdrantClient(
            host=host, port=port, prefer_grpc=prefer_grpc, timeout=30,
            check_compatibility=False,  # server 1.17.x with client 1.15.x works fine
        )
        self._embedding_dim = self.embedding_func.embedding_dim
        self._max_batch_size = self.global_config.get("embedding_batch_num", 32)

    async def initialize(self):
        """Create collection + payload indexes if not already exist."""
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config={
                    "dense": VectorParams(
                        size=self._embedding_dim,
                        distance=Distance.COSINE,
                        on_disk=False,
                    )
                },
                sparse_vectors_config={
                    "sparse": SparseVectorParams(
                        index=SparseIndexParams(on_disk=False)
                    )
                },
            )
            for fname, fschema in _INDEX_FIELDS:
                self._client.create_payload_index(
                    collection_name=self._collection,
                    field_name=fname,
                    field_schema=fschema,
                )
            logger.info("Created Qdrant collection: %s", self._collection)

    # ── LightRAG BaseVectorStorage interface ────────────────────────────

    async def upsert(self, data: dict[str, dict[str, Any]]) -> None:
        """Standard LightRAG upsert — used by entity/relation vectors.

        data: {entity_id: {content: str, embedding: list[float], **meta}}
        """
        if not data:
            return

        points = []
        for entity_id, entity_data in data.items():
            embedding = entity_data.get("embedding")
            if embedding is None:
                embedding = await self.embedding_func([entity_data.get("content", "")])[0]

            payload = {k: v for k, v in entity_data.items() if k != "embedding"}
            payload["entity_id"] = entity_id

            points.append(
                PointStruct(
                    id=_to_uuid(entity_id),
                    vector={"dense": embedding},
                    payload=payload,
                )
            )

        self._client.upsert(collection_name=self._collection, points=points, wait=True)

    async def upsert_legal_chunks(self, embedded: list[dict]) -> None:
        """Upsert legal chunks with both dense + sparse vectors.

        embedded: output of LegalEmbedder.embed_chunks()
          → list of {chunk: LegalChunk, dense_vector: list, sparse_vector: dict}
        """
        if not embedded:
            return

        points = []
        for item in embedded:
            chunk = item["chunk"]
            dense = item["dense_vector"]
            sparse_raw = item.get("sparse_vector", {})

            # Convert sparse dict {token_id: weight} → Qdrant SparseVector
            if sparse_raw:
                indices = [int(k) for k in sparse_raw.keys()]
                values = [float(v) for v in sparse_raw.values()]
                sparse_vec = SparseVector(indices=indices, values=values)
            else:
                sparse_vec = SparseVector(indices=[], values=[])

            payload = chunk.to_payload()

            points.append(
                PointStruct(
                    id=_to_uuid(chunk.chunk_id),
                    vector={"dense": dense, "sparse": sparse_vec},
                    payload=payload,
                )
            )

        # Batch upsert
        batch_size = 128
        for i in range(0, len(points), batch_size):
            self._client.upsert(
                collection_name=self._collection,
                points=points[i : i + batch_size],
                wait=True,
            )

    async def query(
        self,
        query: str,
        top_k: int = 10,
        query_embedding: Optional[list[float]] = None,
    ) -> list[dict[str, Any]]:
        """Dense semantic search — fallback for LightRAG entity queries."""
        if query_embedding is None:
            query_embedding = (await self.embedding_func([query]))[0]

        results = self._client.search(
            collection_name=self._collection,
            query_vector=("dense", query_embedding),
            limit=top_k,
            with_payload=True,
            score_threshold=self.cosine_better_than_threshold,
        )

        return [
            {**r.payload, "score": r.score, "id": str(r.id)}
            for r in results
            if r.payload
        ]

    async def query_legal(
        self,
        query: str,
        top_k: int = 20,
        doc_type: Optional[str] = None,
        issuer: Optional[str] = None,
        doc_numbers: Optional[list[str]] = None,
        effective_after: Optional[str] = None,
        chunk_level: Optional[str] = None,
        use_hybrid: bool = True,
    ) -> list[dict[str, Any]]:
        """Hybrid search với legal metadata filtering.

        Returns top_k chunks, sorted by RRF-fused score (dense + sparse).
        """
        import asyncio
        from legal_rag.chunking.embedder import get_embedder

        embedder = get_embedder()
        # embed_query uses a blocking HTTP call — run in thread to avoid blocking event loop
        dense_vec, sparse_raw = await asyncio.to_thread(embedder.embed_query, query)

        # Build payload filter
        conditions = []
        if doc_type:
            conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
        if issuer:
            conditions.append(FieldCondition(key="issuer", match=MatchValue(value=issuer)))
        if doc_numbers:
            conditions.append(FieldCondition(key="doc_number", match=MatchAny(any=doc_numbers)))
        if effective_after:
            conditions.append(FieldCondition(key="effective_date", range=Range(gte=effective_after)))
        if chunk_level:
            conditions.append(FieldCondition(key="chunk_level", match=MatchValue(value=chunk_level)))

        query_filter = Filter(must=conditions) if conditions else None

        if use_hybrid and sparse_raw:
            # Hybrid: dense + sparse via prefetch + RRF fusion
            sparse_vec = SparseVector(
                indices=[int(k) for k in sparse_raw.keys()],
                values=[float(v) for v in sparse_raw.values()],
            )
            results = self._client.query_points(
                collection_name=self._collection,
                prefetch=[
                    qmodels.Prefetch(
                        query=dense_vec,
                        using="dense",
                        limit=top_k * 2,
                        filter=query_filter,
                    ),
                    qmodels.Prefetch(
                        query=sparse_vec,
                        using="sparse",
                        limit=top_k * 2,
                        filter=query_filter,
                    ),
                ],
                query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
                limit=top_k,
                with_payload=True,
            ).points
        else:
            results = self._client.search(
                collection_name=self._collection,
                query_vector=("dense", dense_vec),
                query_filter=query_filter,
                limit=top_k,
                with_payload=True,
                score_threshold=self.cosine_better_than_threshold,
            )

        return [
            {**r.payload, "score": r.score, "id": str(r.id)}
            for r in results
            if r.payload
        ]

    async def get_parent_chunk(self, parent_id: str) -> Optional[dict[str, Any]]:
        """Lấy parent chunk (Điều) từ chunk_id."""
        results = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="chunk_id", match=MatchValue(value=parent_id))]
            ),
            limit=1,
            with_payload=True,
        )
        points = results[0]
        return points[0].payload if points else None

    async def get_chunks_by_article(
        self,
        doc_number: str,
        article: str,
        chunk_level: Optional[str] = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Exact lookup: find chunks by doc_number + article (deterministic).

        Uses payload filtering only — no semantic search involved.
        This is the safe path for exact legal references like "Điều 18 Luật Đất đai 2024".
        """
        conditions = [
            FieldCondition(key="doc_number", match=MatchValue(value=doc_number)),
            FieldCondition(key="article", match=MatchValue(value=article)),
        ]
        if chunk_level:
            conditions.append(
                FieldCondition(key="chunk_level", match=MatchValue(value=chunk_level))
            )

        results, _ = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(must=conditions),
            limit=limit,
            with_payload=True,
        )

        return [
            {**r.payload, "score": 1.0, "id": str(r.id)}
            for r in results
            if r.payload
        ]

    # ── Legal document-level operations ─────────────────────────────────

    async def list_documents(
        self,
        doc_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
    ) -> list[dict]:
        """Aggregate chunks by doc_id → return one record per document.

        Returns list of dicts with document-level metadata + chunks_count.
        """
        conditions = []
        if doc_type:
            conditions.append(FieldCondition(key="doc_type", match=MatchValue(value=doc_type)))
        if status:
            conditions.append(FieldCondition(key="status", match=MatchValue(value=status)))
        scroll_filter = Filter(must=conditions) if conditions else None

        # Scroll all chunks (no vector needed — payload only)
        docs: dict[str, dict] = {}
        offset = None
        while True:
            results, next_offset = self._client.scroll(
                collection_name=self._collection,
                scroll_filter=scroll_filter,
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in results:
                p = point.payload or {}
                doc_id = p.get("doc_id", "")
                if not doc_id:
                    continue
                if doc_id not in docs:
                    docs[doc_id] = {
                        "doc_id": doc_id,
                        "doc_number": p.get("doc_number", ""),
                        "doc_type": p.get("doc_type", ""),
                        "issuer": p.get("issuer", ""),
                        "issue_date": p.get("issue_date", ""),
                        "effective_date": p.get("effective_date", ""),
                        "status": p.get("status", "HIEU_LUC"),
                        "is_primary_source": p.get("is_primary_source", True),
                        "legal_priority": p.get("legal_priority", 0.0),
                        "chunks_count": 0,
                    }
                docs[doc_id]["chunks_count"] += 1

            if next_offset is None or len(docs) >= limit:
                break
            offset = next_offset

        return list(docs.values())[:limit]

    async def update_document_metadata(
        self,
        doc_id: str,
        updates: dict,
    ) -> int:
        """Update payload fields for all chunks of a document.

        Returns number of affected chunks.
        """
        # Count first
        count_result = self._client.count(
            collection_name=self._collection,
            count_filter=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
            exact=True,
        )
        n = count_result.count

        if n == 0:
            return 0

        # Remove read-only / derived fields that should not be written
        safe_updates = {
            k: v for k, v in updates.items()
            if k in {
                "doc_type", "doc_number", "issuer", "issue_date",
                "effective_date", "status", "is_primary_source",
                "legal_priority", "authority_score",
            }
        }

        if safe_updates:
            self._client.set_payload(
                collection_name=self._collection,
                payload=safe_updates,
                points=qmodels.FilterSelector(
                    filter=Filter(
                        must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                    )
                ),
            )

        return n

    async def delete_document(self, doc_id: str) -> int:
        """Delete all chunks belonging to doc_id. Returns chunk count deleted."""
        count_result = self._client.count(
            collection_name=self._collection,
            count_filter=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
            exact=True,
        )
        n = count_result.count

        if n > 0:
            self._client.delete(
                collection_name=self._collection,
                points_selector=qmodels.FilterSelector(
                    filter=Filter(
                        must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
                    )
                ),
            )
        return n

    async def delete_entity(self, entity_name: str) -> None:
        self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="entity_name", match=MatchValue(value=entity_name))]
                )
            ),
        )

    async def delete_entity_relation(self, entity_name: str) -> None:
        self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.FilterSelector(
                filter=Filter(
                    must=[FieldCondition(key="src_id", match=MatchValue(value=entity_name))]
                )
            ),
        )

    async def get_by_id(self, id: str) -> Optional[dict[str, Any]]:
        results = self._client.retrieve(
            collection_name=self._collection,
            ids=[_to_uuid(id)],
            with_payload=True,
        )
        return results[0].payload if results else None

    async def get_by_ids(self, ids: list[str]) -> list[dict[str, Any]]:
        results = self._client.retrieve(
            collection_name=self._collection,
            ids=[_to_uuid(i) for i in ids],
            with_payload=True,
        )
        return [r.payload for r in results if r.payload]

    async def delete(self, ids: list[str]) -> None:
        self._client.delete(
            collection_name=self._collection,
            points_selector=qmodels.PointIdsList(
                points=[_to_uuid(i) for i in ids]
            ),
        )

    async def drop(self) -> dict[str, str]:
        try:
            self._client.delete_collection(self._collection)
            logger.info("Dropped Qdrant collection: %s", self._collection)
            return {"status": "success", "message": "data dropped"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def get_vectors_by_ids(self, ids: list[str]) -> dict[str, list[float]]:
        results = self._client.retrieve(
            collection_name=self._collection,
            ids=[_to_uuid(i) for i in ids],
            with_payload=False,
            with_vectors=["dense"],
        )
        out: dict[str, list[float]] = {}
        for r in results:
            if not r.vector:
                continue
            vec = r.vector["dense"] if isinstance(r.vector, dict) else r.vector
            out[str(r.id)] = vec
        return out

    async def index_done_callback(self, **kwargs) -> None:
        pass  # Qdrant persists synchronously


def _to_uuid(text: str) -> str:
    """Convert arbitrary string ID → UUID-format string (deterministic)."""
    h = hashlib.md5(text.encode()).hexdigest()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"
