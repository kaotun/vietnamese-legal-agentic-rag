"""
vector_store.py — FAISS Vector Store Wrapper

Nhiệm vụ: Wrap FAISS index với API query đơn giản.
Load FAISS index từ disk và cung cấp method search() trả về chunk_id.

Tại sao cần wrapper này?
- FAISS trả về integer index (vị trí trong mảng), không phải chunk_id
- Wrapper này map từ integer index → chunk_id → LegalChunk
- Cung cấp API nhất quán với BM25Index để Phase 2 có thể kết hợp dễ dàng
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from src.common.schemas import LegalChunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

DEFAULT_INDEX_DIR = "data/processed"
FAISS_INDEX_FILE = "faiss_index.bin"
CHUNK_STORE_FILE = "chunk_store.jsonl"


# ---------------------------------------------------------------------------
# VectorStore class
# ---------------------------------------------------------------------------


class VectorStore:
    """
    Wrapper quanh FAISS index với chunk metadata.

    Ví dụ sử dụng:
        store = VectorStore.load("data/processed")
        query_vector = embedder.encode_query("điều kiện hợp đồng lao động")
        results = store.search(query_vector, top_k=10)
        for chunk_id, score in results:
            chunk = store.get_chunk(chunk_id)
            print(chunk.text[:200])
    """

    def __init__(self):
        self._index = None                   # faiss.Index
        self._chunks: List[LegalChunk] = []  # ordered list — vị trí = FAISS index
        self._chunk_id_map: dict = {}        # chunk_id → vị trí trong list

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------

    @classmethod
    def load(cls, index_dir: str | Path = DEFAULT_INDEX_DIR) -> "VectorStore":
        """
        Load FAISS index và chunk metadata từ disk.

        Args:
            index_dir: Thư mục chứa faiss_index.bin và chunk_store.jsonl
        """
        import faiss

        index_dir = Path(index_dir)
        index_path = index_dir / FAISS_INDEX_FILE
        chunk_store_path = index_dir / CHUNK_STORE_FILE

        if not index_path.exists():
            raise FileNotFoundError(f"Không tìm thấy FAISS index: {index_path}")
        if not chunk_store_path.exists():
            raise FileNotFoundError(f"Không tìm thấy chunk store: {chunk_store_path}")

        instance = cls()

        # Load FAISS index
        instance._index = faiss.read_index(str(index_path))
        logger.info(
            "VectorStore: loaded FAISS index — %d vectors, dim=%d",
            instance._index.ntotal,
            instance._index.d,
        )

        # Load chunk metadata
        with open(chunk_store_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                chunk = LegalChunk(**data)
                pos = len(instance._chunks)
                instance._chunks.append(chunk)
                instance._chunk_id_map[chunk.chunk_id] = pos

        logger.info("VectorStore: loaded %d chunks metadata", len(instance._chunks))
        return instance

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self, query_vector: np.ndarray, top_k: int = 20
    ) -> List[Tuple[str, float]]:
        """
        Tìm kiếm vector tương tự nhất trong FAISS index.

        Args:
            query_vector: np.ndarray shape (dim,) — đã normalize
            top_k: Số kết quả trả về

        Returns:
            List of (chunk_id, score) — đã sắp xếp theo score giảm dần
            score ∈ [-1, 1] (cosine similarity sau normalize)
        """
        if self._index is None:
            raise RuntimeError("VectorStore chưa được load. Gọi VectorStore.load() trước.")

        # FAISS cần input shape (1, dim)
        query = query_vector.reshape(1, -1).astype(np.float32)
        scores, indices = self._index.search(query, top_k)

        results = []
        for score, idx in zip(scores[0], indices[0]):
            if idx == -1:  # FAISS trả -1 nếu không đủ kết quả
                continue
            if idx >= len(self._chunks):
                continue
            chunk_id = self._chunks[idx].chunk_id
            results.append((chunk_id, float(score)))

        return results

    # ------------------------------------------------------------------
    # Chunk access
    # ------------------------------------------------------------------

    def get_chunk(self, chunk_id: str) -> Optional[LegalChunk]:
        """Lấy LegalChunk theo chunk_id."""
        pos = self._chunk_id_map.get(chunk_id)
        if pos is None:
            return None
        return self._chunks[pos]

    def get_all_chunks(self) -> List[LegalChunk]:
        """Trả về toàn bộ chunks theo thứ tự trong index."""
        return self._chunks

    @property
    def total_chunks(self) -> int:
        return len(self._chunks)
