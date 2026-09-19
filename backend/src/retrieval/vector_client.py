"""Client phục vụ việc tạo vector nhúng (Embeddings) qua chuẩn OpenAI-compatible."""
from __future__ import annotations

import logging
from typing import List
import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingsClient:
    """Client gọi endpoint Embedding theo chuẩn OpenAI (POST /v1/embeddings)."""

    def __init__(self, base_url: str | None = None, model: str | None = None, api_key: str | None = None):
        settings = get_settings()
        self.base_url = (base_url or settings.embeddings.base_url).rstrip("/")
        self.model = model or settings.embeddings.model
        self.api_key = api_key or settings.embeddings.api_key
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

    async def close(self) -> None:
        await self.client.aclose()
