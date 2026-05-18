"""Legal ingestion & search endpoints.

Các endpoint này tách biệt với LightRAG core để xử lý:
  - Ingest PDF với legal chunking pipeline (Qdrant + Neo4j)
  - Hybrid search với filter metadata pháp lý
  - Graph traversal tìm văn bản liên quan
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from lightrag.api.utils_api import get_combined_auth_dependency


# ── Request/Response models ──────────────────────────────────────────

class DocMeta(BaseModel):
    doc_number: str = Field(..., description="Số hiệu văn bản, vd: 13/2023/NĐ-CP")
    doc_type: str = Field(..., description="Loại văn bản: Nghị định / Thông tư / Luật ...")
    issuer: str = Field(..., description="Cơ quan ban hành")
    issue_date: str = Field(..., description="Ngày ban hành, ISO: 2023-04-17")
    effective_date: str = Field(default="", description="Ngày có hiệu lực")
    title: str = Field(default="", description="Tên văn bản")
    legal_domain: list[str] = Field(default_factory=list, description="Lĩnh vực pháp lý")
    status: str = Field(default="HIEU_LUC", description="HIEU_LUC / HET_HIEU_LUC")
    doc_id: Optional[str] = Field(default=None, description="ID tùy chỉnh (tự sinh nếu để trống)")


class IngestResponse(BaseModel):
    doc_id: str
    qdrant_chunks: Optional[dict] = None
    lightrag_status: Optional[str] = None
    graph_relations: Optional[int] = None
    errors: list[str] = Field(default_factory=list)


class LegalSearchRequest(BaseModel):
    query: str
    top_k: int = Field(default=10, ge=1, le=50)
    doc_type: Optional[str] = None
    issuer: Optional[str] = None
    doc_numbers: Optional[list[str]] = None
    effective_after: Optional[str] = None
    chunk_level: Optional[str] = Field(default=None, description="'parent' hoặc 'child'")
    use_hybrid: bool = Field(default=True, description="Dùng hybrid search (dense + BM25)")


class LegalQueryRequest(BaseModel):
    question: str = Field(..., description="Câu hỏi pháp lý (tiếng Việt)")
    conversation_history: list[dict] = Field(
        default_factory=list,
        description="Lịch sử hội thoại [{role, content}]",
    )
    # Pipeline config overrides
    top_k: int = Field(default=20, ge=1, le=100)
    enable_rerank: bool = Field(default=True)
    rerank_top_k: int = Field(default=10, ge=1, le=50)
    enable_judge: bool = Field(default=True)
    max_retries: int = Field(default=2, ge=0, le=5)
    confidence_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    enable_verification: bool = Field(default=True)
    enable_lightrag: bool = Field(default=True)
    enable_graph: bool = Field(default=False)
    # Phase 2: new config fields
    enable_dependency_resolution: bool = Field(default=True, description="Bật cross-reference expansion")
    enable_conflict_detection: bool = Field(default=True, description="Bật phát hiện xung đột pháp lý")
    enable_claim_verification: bool = Field(default=True, description="Bật xác minh từng khẳng định")
    enable_citation_validation: bool = Field(default=True, description="Bật xác minh citation")
    max_graph_depth: int = Field(default=2, ge=1, le=5, description="Độ sâu traversal Neo4j tối đa")
    max_graph_neighbors: int = Field(default=10, ge=1, le=50, description="Số văn bản liên quan tối đa")
    # Step 6.5: Legal scoring config
    enable_legal_scoring: bool = Field(default=True, description="Bật legal-aware composite scoring")
    exclude_expired: bool = Field(
        default=False,
        description="Loại hẳn văn bản HET_HIEU_LUC/BI_THAY_THE khỏi context",
    )
    min_legal_score: float = Field(
        default=0.0, ge=0.0, le=1.0,
        description="Ngưỡng composite score tối thiểu (0 = không lọc)",
    )
    legal_score_weights: Optional[dict] = Field(
        default=None,
        description=(
            "Trọng số scoring tùy chỉnh. Mặc định: "
            "{semantic:0.45, legal_priority:0.30, authority:0.15, recency:0.10}"
        ),
    )
    # Metadata filters
    doc_type: Optional[str] = None
    issuer: Optional[str] = None
    doc_numbers: Optional[list[str]] = None
    effective_after: Optional[str] = None
    chunk_level: Optional[str] = None


class RelatedDocsRequest(BaseModel):
    doc_number: str
    status_filter: str = Field(default="HIEU_LUC")


class UpdateDocMetaRequest(BaseModel):
    doc_type: Optional[str] = None
    doc_number: Optional[str] = None
    issuer: Optional[str] = None
    issue_date: Optional[str] = None
    effective_date: Optional[str] = None
    status: Optional[str] = Field(
        default=None,
        description="HIEU_LUC / HET_HIEU_LUC / BI_THAY_THE / SAP_HIEU_LUC",
    )
    is_primary_source: Optional[bool] = None


class LegalDocumentItem(BaseModel):
    doc_id: str
    doc_number: str
    doc_type: str
    issuer: str
    issue_date: str
    effective_date: str
    status: str
    is_primary_source: bool
    legal_priority: float
    chunks_count: int


# ── Router factory ───────────────────────────────────────────────────

def create_legal_routes(api_key: Optional[str] = None):
    router = APIRouter(prefix="/legal", tags=["legal"])
    combined_auth = get_combined_auth_dependency(api_key)

    @router.post("/ingest/pdf", response_model=IngestResponse, dependencies=[Depends(combined_auth)])
    async def ingest_pdf(
        file: UploadFile = File(...),
        doc_number: str = "",
        doc_type: str = "Nghị định",
        issuer: str = "",
        issue_date: str = "",
        effective_date: str = "",
        title: str = "",
        legal_domain: str = "",   # comma-separated
        enable_contextual: bool = True,
        enable_graph: bool = False,
        use_ocr: bool = False,    # ép dùng OCR API thay vì pdfplumber
    ):
        """Ingest một file PDF hoặc ảnh vào hệ thống với legal chunking pipeline.

        Hỗ trợ:
          - PDF text-based: pdfplumber (mặc định)
          - PDF scan: tự phát hiện text thưa → OCR API tự động
          - Ảnh (PNG/JPG/TIFF/...): OCR API
          - use_ocr=true: ép dùng OCR bất kể loại file

        Chạy song song:
          - Qdrant: structure-aware chunking + BGE-M3 embed + hybrid index
          - LightRAG: entity/relation extraction → knowledge graph
          - Neo4j: inter-document relation extraction (nếu enable_graph=True)
        """
        from legal_rag.ingestion.legal_indexer import LegalDocumentIndexer
        from legal_rag.chunking.ocr_client import IMAGE_EXTENSIONS
        from legal_rag.chunking.pipeline import DOCX_EXTENSIONS, MD_EXTENSIONS, TEXT_EXTENSIONS
        from pathlib import Path

        if not file.filename:
            raise HTTPException(status_code=400, detail="Tên file không hợp lệ")

        ext = Path(file.filename).suffix.lower()
        allowed = {".pdf"} | IMAGE_EXTENSIONS | DOCX_EXTENSIONS | MD_EXTENSIONS | TEXT_EXTENSIONS
        if ext not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Định dạng không hỗ trợ: {ext}. Hỗ trợ: {', '.join(sorted(allowed))}",
            )

        doc_meta = {
            "doc_number": doc_number or Path(file.filename).stem,
            "doc_type": doc_type,
            "issuer": issuer,
            "issue_date": issue_date,
            "effective_date": effective_date,
            "title": title or file.filename,
            "legal_domain": [d.strip() for d in legal_domain.split(",") if d.strip()],
        }

        # Save uploaded file to temp (preserve original extension for MIME detection)
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            content = await file.read()
            tmp.write(content)
            tmp_path = tmp.name

        try:
            qdrant = _get_qdrant_storage()
            rag = _get_default_rag()
            indexer = LegalDocumentIndexer(
                rag=rag,
                qdrant=qdrant,
                graph_builder=_get_graph_builder() if enable_graph else None,
                enable_contextual=enable_contextual,
                enable_graph=enable_graph,
                use_ocr=use_ocr,
            )

            result = await indexer.ingest_pdf(tmp_path, doc_meta)
        finally:
            os.unlink(tmp_path)

        errors = [v for k, v in result.items() if k.endswith("_error")]
        return IngestResponse(
            doc_id=result["doc_id"],
            qdrant_chunks=result.get("qdrant_chunks"),
            lightrag_status=result.get("lightrag_status"),
            graph_relations=result.get("graph_relations"),
            errors=errors,
        )

    @router.post("/query", dependencies=[Depends(combined_auth)])
    async def legal_query_endpoint(req: LegalQueryRequest):
        """Full Legal RAG Query Pipeline.

        9-step pipeline:
          1. Query Rewrite
          2. Hybrid Retrieval (Qdrant + LightRAG + Neo4j)
          3. Rerank
          4. LLM Relevance Judge
          5. Retry Retrieval (if needed, max N retries)
          6. Grounded Generation
          7. Citation Attachment
          8. Self-Grounding Verification
          9. Final Answer (or rejection if confidence < threshold)
        """
        from legal_rag.query import legal_query, PipelineConfig

        _default_weights = {
            "semantic": 0.45,
            "legal_priority": 0.30,
            "authority": 0.15,
            "recency": 0.10,
        }
        pipeline_config = PipelineConfig(
            top_k=req.top_k,
            enable_rerank=req.enable_rerank,
            rerank_top_k=req.rerank_top_k,
            enable_judge=req.enable_judge,
            max_retries=req.max_retries,
            confidence_threshold=req.confidence_threshold,
            enable_verification=req.enable_verification,
            enable_lightrag=req.enable_lightrag,
            enable_graph=req.enable_graph,
            # Phase 2 config
            enable_dependency_resolution=req.enable_dependency_resolution,
            enable_conflict_detection=req.enable_conflict_detection,
            enable_claim_verification=req.enable_claim_verification,
            enable_citation_validation=req.enable_citation_validation,
            max_graph_depth=req.max_graph_depth,
            max_graph_neighbors=req.max_graph_neighbors,
            # Step 6.5: Legal scoring
            enable_legal_scoring=req.enable_legal_scoring,
            exclude_expired=req.exclude_expired,
            min_legal_score=req.min_legal_score,
            legal_score_weights=req.legal_score_weights or _default_weights,
            # Metadata filters
            doc_type=req.doc_type,
            issuer=req.issuer,
            doc_numbers=req.doc_numbers,
            effective_after=req.effective_after,
            chunk_level=req.chunk_level,
        )

        qdrant = _get_qdrant_storage()
        rag = _get_default_rag()
        graph = _get_graph_builder() if req.enable_graph else None

        result = await legal_query(
            question=req.question,
            config=pipeline_config,
            qdrant=qdrant,
            rag=rag,
            graph_builder=graph,
            conversation_history=req.conversation_history or None,
        )

        return result.to_dict()

    @router.post("/search", dependencies=[Depends(combined_auth)])
    async def legal_search(req: LegalSearchRequest):
        """Hybrid search trực tiếp trong Qdrant với filter pháp lý.

        Trả về danh sách chunks kèm metadata (điều/khoản/trang/dòng).
        """
        qdrant = _get_qdrant_storage()
        results = await qdrant.query_legal(
            query=req.query,
            top_k=req.top_k,
            doc_type=req.doc_type,
            issuer=req.issuer,
            doc_numbers=req.doc_numbers,
            effective_after=req.effective_after,
            chunk_level=req.chunk_level,
            use_hybrid=req.use_hybrid,
        )
        return {"results": results, "count": len(results)}

    @router.post("/graph/related", dependencies=[Depends(combined_auth)])
    async def get_related_docs(req: RelatedDocsRequest):
        """Traverse Neo4j để tìm văn bản liên quan."""
        builder = _get_graph_builder()
        if builder is None:
            raise HTTPException(status_code=503, detail="Neo4j chưa được cấu hình")
        related = await builder.get_related_documents(
            req.doc_number, status_filter=req.status_filter
        )
        return {"doc_number": req.doc_number, "related": related}

    @router.get("/graph/history/{doc_number}", dependencies=[Depends(combined_auth)])
    async def get_doc_history(doc_number: str):
        """Lịch sử sửa đổi / thay thế của một văn bản."""
        builder = _get_graph_builder()
        if builder is None:
            raise HTTPException(status_code=503, detail="Neo4j chưa được cấu hình")
        history = await builder.get_document_history(doc_number)
        return {"doc_number": doc_number, "history": history}

    @router.get("/graph/domain/{domain}", dependencies=[Depends(combined_auth)])
    async def docs_by_domain(domain: str, status: str = "HIEU_LUC"):
        """Tìm văn bản theo lĩnh vực pháp lý."""
        builder = _get_graph_builder()
        if builder is None:
            raise HTTPException(status_code=503, detail="Neo4j chưa được cấu hình")
        docs = await builder.find_documents_by_domain(domain, status)
        return {"domain": domain, "documents": docs}

    # ── Document CRUD ────────────────────────────────────────────────

    @router.get("/documents", response_model=list[LegalDocumentItem], dependencies=[Depends(combined_auth)])
    async def list_legal_documents(
        doc_type: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 500,
    ):
        """Danh sách tất cả văn bản pháp lý đã index trong Qdrant.

        Mỗi record đại diện cho một văn bản (tổng hợp từ các chunks).
        """
        qdrant = _get_qdrant_storage()
        docs = await qdrant.list_documents(doc_type=doc_type, status=status, limit=limit)
        return docs

    @router.patch("/documents/{doc_id}", dependencies=[Depends(combined_auth)])
    async def update_legal_document(doc_id: str, body: UpdateDocMetaRequest):
        """Cập nhật metadata cho toàn bộ chunks của một văn bản.

        Chỉ các field được truyền vào mới được cập nhật (partial update).
        """
        qdrant = _get_qdrant_storage()
        updates = body.model_dump(exclude_unset=True, exclude_none=True)
        if not updates:
            raise HTTPException(status_code=400, detail="Không có field nào để cập nhật")
        updated = await qdrant.update_document_metadata(doc_id, updates)
        if updated == 0:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy doc_id: {doc_id}")
        return {"doc_id": doc_id, "updated_chunks": updated, "updates": updates}

    @router.delete("/documents/{doc_id}", dependencies=[Depends(combined_auth)])
    async def delete_legal_document(doc_id: str):
        """Xoá toàn bộ chunks của một văn bản khỏi Qdrant."""
        qdrant = _get_qdrant_storage()
        deleted = await qdrant.delete_document(doc_id)
        if deleted == 0:
            raise HTTPException(status_code=404, detail=f"Không tìm thấy doc_id: {doc_id}")
        return {"doc_id": doc_id, "deleted_chunks": deleted}

    return router


# ── Lazy singletons (set by server on startup) ───────────────────────

_qdrant_storage = None
_default_rag = None
_graph_builder = None


def set_legal_singletons(qdrant=None, rag=None, graph_builder=None):
    global _qdrant_storage, _default_rag, _graph_builder
    if qdrant is not None:
        _qdrant_storage = qdrant
    if rag is not None:
        _default_rag = rag
    if graph_builder is not None:
        _graph_builder = graph_builder


def _get_qdrant_storage():
    if _qdrant_storage is None:
        raise HTTPException(
            status_code=503,
            detail="QdrantLegalVectorStorage chưa khởi tạo. "
                   "Set QDRANT_HOST + QDRANT_PORT và khởi động lại server.",
        )
    return _qdrant_storage


def _get_default_rag():
    if _default_rag is None:
        raise HTTPException(status_code=503, detail="LightRAG instance chưa sẵn sàng")
    return _default_rag


def _get_graph_builder():
    return _graph_builder
