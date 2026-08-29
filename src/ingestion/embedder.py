"""
embedder.py — Document Embedder

Nhiệm vụ: Encode List[LegalChunk] → vector embeddings → lưu FAISS index.

Luồng:
  List[LegalChunk]
      └─► SentenceTransformer encode (batch)
          └─► normalize vectors (để dùng cosine similarity)
              └─► FAISS IndexFlatIP
                  ├─► lưu index xuống disk
                  └─► lưu chunk metadata (chunk_id mapping) xuống disk
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from src.common.schemas import LegalChunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

# Model mặc định: tiếng Việt chuyên biệt (~400MB)
DEFAULT_MODEL = "keepitreal/vietnamese-sbert"

# Model nhẹ hơn để test nhanh (~120MB, đa ngôn ngữ)
LIGHTWEIGHT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

DEFAULT_BATCH_SIZE = 32

# Đường dẫn lưu index mặc định
DEFAULT_INDEX_DIR = "data/processed"
FAISS_INDEX_FILE = "faiss_index.bin"
CHUNK_STORE_FILE = "chunk_store.jsonl"


# ---------------------------------------------------------------------------
# Embedder class
# ---------------------------------------------------------------------------


class DocumentEmbedder:
    """
    Encode chunks thành vector embedding và build FAISS index.

    Ví dụ sử dụng:
        embedder = DocumentEmbedder()
        embedder.build_index(chunks, output_dir="data/processed")
    """

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ):
        self.model_name = model_name
        self.batch_size = batch_size
        self._model = None  # lazy load

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_index(
        self,
        chunks: List[LegalChunk],
        output_dir: str | Path = DEFAULT_INDEX_DIR,
    ) -> None:
        """
        Encode toàn bộ chunks và lưu FAISS index + metadata ra disk.

        Args:
            chunks: List[LegalChunk] từ Chunker
            output_dir: Thư mục lưu FAISS index và chunk metadata
        """
        import faiss

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        if not chunks:
            logger.warning("Embedder: không có chunk nào để encode")
            return

        logger.info("Embedder: bắt đầu encode %d chunks với model '%s'", len(chunks), self.model_name)

        # Bước 1: Lấy text để embed (dùng to_index_text để thêm article_ref)
        texts = [chunk.to_index_text() for chunk in chunks]

        # Bước 2: Encode batch
        t0 = time.time()
        embeddings = self._encode(texts)
        encode_time = time.time() - t0
        logger.info(
            "Embedder: encode xong trong %.1f giây (%.2f chunks/giây)",
            encode_time,
            len(chunks) / encode_time,
        )

        # Bước 3: Normalize để dùng Inner Product = Cosine Similarity
        # Tự implement normalization để hiểu cơ chế (không dùng faiss.normalize_L2)
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1, norms)  # tránh chia 0
        normalized = embeddings / norms

        # Bước 4: Build FAISS index
        dim = normalized.shape[1]
        index = faiss.IndexFlatIP(dim)  # Inner Product (cosine sau normalize)
        index.add(normalized.astype(np.float32))
        logger.info(
            "Embedder: FAISS index built — %d vectors, dim=%d, size=%.1fMB",
            index.ntotal,
            dim,
            (index.ntotal * dim * 4) / (1024 ** 2),
        )

        # Bước 5: Lưu index xuống disk
        index_path = output_dir / FAISS_INDEX_FILE
        faiss.write_index(index, str(index_path))
        logger.info("Embedder: lưu FAISS index → %s", index_path)

        # Bước 6: Lưu chunk metadata (chunk_id → vị trí trong index)
        # Cần để map kết quả FAISS (integer index) về chunk_id thực
        chunk_store_path = output_dir / CHUNK_STORE_FILE
        self._save_chunk_store(chunks, chunk_store_path)
        logger.info("Embedder: lưu chunk metadata → %s", chunk_store_path)

    def encode_query(self, query: str) -> np.ndarray:
        """
        Encode một câu query để dùng trong search.

        Returns:
            np.ndarray shape (dim,) — đã normalize, sẵn sàng để query FAISS
        """
        embedding = self._encode([query])[0]
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        return embedding.astype(np.float32)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _get_model(self):
        """Lazy load SentenceTransformer model."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            logger.info("Embedder: loading model '%s'...", self.model_name)
            self._model = SentenceTransformer(self.model_name)
        return self._model

    def _encode(self, texts: List[str]) -> np.ndarray:
        """
        Encode danh sách text thành ma trận embedding.

        Returns:
            np.ndarray shape (n, dim)
        """
        model = self._get_model()
        embeddings = model.encode(
            texts,
            batch_size=self.batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
        )
        return embeddings

    def _save_chunk_store(
        self, chunks: List[LegalChunk], path: Path
    ) -> None:
        """
        Lưu mapping: FAISS integer index → chunk data.
        Format: mỗi dòng là một JSON object đại diện 1 chunk.
        Thứ tự dòng = thứ tự trong FAISS index.
        """
        with open(path, "w", encoding="utf-8") as f:
            for chunk in chunks:
                # Serialize chunk thành dict, lưu đủ thông tin để reconstruct
                record = {
                    "chunk_id": chunk.chunk_id,
                    "doc_id": chunk.doc_id,
                    "text": chunk.text,
                    "article_ref": chunk.article_ref,
                    "char_len": chunk.char_len,
                    "chunk_index": chunk.chunk_index,
                    "metadata": chunk.metadata,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
