"""Tầng 4 — BGE-M3 Embedder.

Sinh đồng thời:
  - Dense vector (1024 dim) → semantic search
  - Sparse vector (BM25-style) → keyword/lexical search

Ưu tiên FlagEmbedding local (nếu được cài). Nếu không có (môi trường Docker
dùng remote server), tự động dùng remote OpenAI-compatible embedding API.
Khi dùng remote: sparse vector = {} → query_legal tự chuyển về dense-only search.
"""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from legal_rag.models.chunk import LegalChunk

try:
    from FlagEmbedding import BGEM3FlagModel  # type: ignore
    _HAS_FLAG_EMBEDDING = True
except ImportError:
    _HAS_FLAG_EMBEDDING = False


class LegalEmbedder:
    """BGE-M3 embedder — local FlagEmbedding hoặc remote server fallback."""

    def __init__(self, model_name: str = "BAAI/bge-m3", use_fp16: bool = True):
        self.model_name = model_name
        self._model = None
        self._use_fp16 = use_fp16
        self._remote_client = None
        self._remote_model: str = ""
        self._use_remote = not _HAS_FLAG_EMBEDDING
        if self._use_remote:
            from lightrag.utils import logger
            logger.info(
                "FlagEmbedding not installed — falling back to remote embedding server "
                "(EMBEDDING_BINDING_HOST=%s). Sparse vectors unavailable; "
                "legal search will use dense-only mode.",
                os.getenv("EMBEDDING_BINDING_HOST", "http://localhost:9062/v1"),
            )

    # ── Private: local model ─────────────────────────────────────────────

    def _get_local_model(self) -> "BGEM3FlagModel":
        if self._model is None:
            self._model = BGEM3FlagModel(self.model_name, use_fp16=self._use_fp16)
        return self._model

    # ── Private: remote client ───────────────────────────────────────────

    def _get_remote_client(self):
        if self._remote_client is None:
            import openai  # already a dep via --extra api
            base_url = os.getenv("EMBEDDING_BINDING_HOST", "http://localhost:9062/v1")
            api_key = os.getenv("EMBEDDING_BINDING_API_KEY", "not_needed")
            self._remote_model = os.getenv("EMBEDDING_MODEL", "bge-m3")
            self._remote_client = openai.OpenAI(base_url=base_url, api_key=api_key)
        return self._remote_client

    # ── Public API ────────────────────────────────────────────────────────

    def embed_chunks(
        self,
        chunks: list["LegalChunk"],
        batch_size: int = 32,
    ) -> list[dict]:
        """Embed list chunks → list of {chunk, dense_vector, sparse_vector}."""
        if self._use_remote:
            return self._embed_chunks_remote(chunks, batch_size)
        return self._embed_chunks_local(chunks, batch_size)

    def embed_query(self, query_text: str) -> tuple[list[float], dict]:
        """Embed một query → (dense_vector, sparse_vector).

        Khi dùng remote: sparse_vector = {} → caller tự chọn dense-only search.
        """
        if self._use_remote:
            return self._embed_query_remote(query_text)
        return self._embed_query_local(query_text)

    # ── Local implementations ─────────────────────────────────────────────

    def _embed_chunks_local(self, chunks: list["LegalChunk"], batch_size: int) -> list[dict]:
        texts = [c.text for c in chunks]
        model = self._get_local_model()
        output = model.encode(
            texts,
            batch_size=batch_size,
            max_length=512,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        return [
            {
                "chunk": chunk,
                "dense_vector": output["dense_vecs"][i].tolist(),
                "sparse_vector": dict(output["lexical_weights"][i]),
            }
            for i, chunk in enumerate(chunks)
        ]

    def _embed_query_local(self, query_text: str) -> tuple[list[float], dict]:
        model = self._get_local_model()
        output = model.encode(
            [query_text],
            max_length=512,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
        return output["dense_vecs"][0].tolist(), dict(output["lexical_weights"][0])

    # ── Remote implementations ────────────────────────────────────────────

    @staticmethod
    def _truncate(text: str) -> str:
        """Truncate text to fit within remote embedding model's token limit.

        EMBEDDING_TOKEN_LIMIT tokens × 2 chars/token (conservative for Vietnamese).
        Default 4096 × 2 = 8192 chars → ~3200-3500 tokens, safely under 4096.
        """
        limit = int(os.getenv("EMBEDDING_TOKEN_LIMIT", "4096"))
        max_chars = limit * 2
        return text[:max_chars] if len(text) > max_chars else text

    def _embed_chunks_remote(self, chunks: list["LegalChunk"], batch_size: int) -> list[dict]:
        client = self._get_remote_client()
        results: list[dict] = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [self._truncate(c.text) for c in batch]
            resp = client.embeddings.create(model=self._remote_model, input=texts)
            for j, chunk in enumerate(batch):
                results.append({
                    "chunk": chunk,
                    "dense_vector": resp.data[j].embedding,
                    "sparse_vector": {},  # remote API không có sparse output
                })
        return results

    def _embed_query_remote(self, query_text: str) -> tuple[list[float], dict]:
        client = self._get_remote_client()
        resp = client.embeddings.create(
            model=self._remote_model,
            input=[self._truncate(query_text)],
        )
        return resp.data[0].embedding, {}  # sparse = {} → dense-only search


# Module-level singleton
_embedder: LegalEmbedder | None = None


def get_embedder() -> LegalEmbedder:
    global _embedder
    if _embedder is None:
        _embedder = LegalEmbedder()
    return _embedder
