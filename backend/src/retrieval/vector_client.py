"""Client phục vụ việc tạo vector nhúng (Embeddings) qua chuẩn OpenAI-compatible."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx

from src.core.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingsClient:
    """Client gọi endpoint Embedding theo chuẩn OpenAI (POST /v1/embeddings)."""

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        pool: Any | None = None,
    ):
        settings = get_settings()
        self.base_url = (base_url or settings.embeddings.base_url).rstrip("/")
        self.model = model or settings.embeddings.model
        self.api_key = api_key or settings.embeddings.api_key
        self.pool = pool
        self.client = httpx.AsyncClient(timeout=30.0)


    async def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Gửi danh sách văn bản để lấy danh sách vector embedding."""
        if not texts:
            return []

        url = f"{self.base_url}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.model,
            "input": texts,
        }

        try:
            resp = await self.client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            # Trích xuất embeddings theo thứ tự index
            embeddings = [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
            return embeddings
        except Exception as e:
            logger.warning(f"Lỗi khi gọi embedding endpoint ({url}): {e}")
            return []

    async def embed_query(self, query: str) -> List[float]:
        """Tạo vector cho 1 câu truy vấn."""
        vectors = await self.embed_texts([query])
        return vectors[0] if vectors else []

    async def vector_search(
        self,
        db_url: str,
        query_vector: List[float],
        table_name: str = "legal_knowledge_records",
        top_k: int = 20,
        pool: Any | None = None,
    ) -> List[Dict[str, Any]]:
        """Tìm kiếm ngữ nghĩa bằng cosine similarity trực tiếp trên pgvector.

        Hỗ trợ asyncpg.Pool để tái sử dụng kết nối trong môi trường production tải cao.
        """
        if not query_vector:
            logger.warning("[VectorClient] query_vector rỗng, bỏ qua vector search.")
            return []

        try:
            import asyncpg
        except ImportError:
            logger.error("[VectorClient] Chưa cài asyncpg. Bỏ qua vector search.")
            return []

        # Chuyển list float → chuỗi literal pgvector: '[0.12345678, ...]'
        vector_str = "[" + ",".join(f"{v:.8f}" for v in query_vector) + "]"

        sql = f"""
            SELECT
                id,
                law_id,
                law_name,
                doc_type,
                article,
                article_title,
                content,
                author,
                COALESCE(validity_status, 'active') as validity_status,
                effective_date,
                expiration_date,
                1 - (embedding <=> $1::vector) AS vector_score
            FROM {table_name}
            WHERE embedding IS NOT NULL
              AND COALESCE(validity_status, 'active') IN ('active', 'partially_expired')
            ORDER BY embedding <=> $1::vector
            LIMIT $2;
        """

        try:
            active_pool = pool or self.pool
            if active_pool:
                async with active_pool.acquire() as conn:
                    rows = await conn.fetch(sql, vector_str, top_k)
            else:
                conn = await asyncpg.connect(db_url)
                try:
                    rows = await conn.fetch(sql, vector_str, top_k)
                finally:
                    await conn.close()


            results: List[Dict[str, Any]] = []
            for row in rows:
                record = dict(row)
                record["vector_score"] = float(record.get("vector_score") or 0.0)
                results.append(record)

            logger.info(f"[VectorClient] pgvector search trả về {len(results)} kết quả.")
            return results

        except Exception as e:
            logger.warning(f"[VectorClient] Lỗi pgvector search (bảng thiếu cột embedding?): {e}")
            return []

    async def close(self) -> None:
        await self.client.aclose()
