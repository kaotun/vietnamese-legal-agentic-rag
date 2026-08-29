"""
keyword_search.py — BM25 Keyword Index

Nhiệm vụ: Xây dựng BM25 index từ chunks để tìm kiếm theo từ khóa.
BM25 sẽ là một nửa của Hybrid Search (kết hợp với FAISS ở Phase 2).

BM25 (Best Match 25) là thuật toán ranking dựa trên TF-IDF cải tiến:
- TF (Term Frequency): tần suất từ trong document, có "saturation" (không tăng mãi)
- IDF (Inverse Document Frequency): phạt từ phổ biến, thưởng từ hiếm
- Tham số k1 (độ bão hòa TF) và b (độ ảnh hưởng độ dài document)

So sánh với vector search:
- BM25: tốt với từ khóa chính xác, số điều khoản ("Điều 15", "Nghị định 24")
- Vector: tốt với ngữ nghĩa, paraphrase ("được phép" ≈ "có quyền")
"""

from __future__ import annotations

import json
import logging
import pickle
import time
from pathlib import Path
from typing import List, Optional, Tuple

from src.common.schemas import LegalChunk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

DEFAULT_BM25_FILE = "data/processed/bm25_index.pkl"


# ---------------------------------------------------------------------------
# BM25Index class
# ---------------------------------------------------------------------------


class BM25Index:
    """
    Xây dựng và query BM25 index từ chunks.

    Ví dụ sử dụng:
        index = BM25Index()
        index.build(chunks)
        index.save("data/processed/bm25_index.pkl")

        # Sau này
        index = BM25Index.load("data/processed/bm25_index.pkl")
        results = index.search("điều kiện hợp đồng lao động", top_k=10)
    """

    def __init__(self):
        self._bm25 = None          # BM25Okapi object
        self._chunk_ids: List[str] = []   # mapping: vị trí → chunk_id
        self._chunks: List[LegalChunk] = []  # giữ để reconstruct kết quả

    # ------------------------------------------------------------------
    # Build & persist
    # ------------------------------------------------------------------

    def build(self, chunks: List[LegalChunk]) -> None:
        """
        Build BM25 index từ list chunks.

        Tokenization: dùng split() đơn giản (whitespace).
        Lý do: tiếng Việt không có word boundary rõ ràng như tiếng Anh,
        nhưng split() vẫn hoạt động tốt cho từ khoá pháp luật vì chúng
        thường là các từ đơn lẻ rõ ràng (tên luật, số điều, v.v.).
        """
        from rank_bm25 import BM25Okapi

        if not chunks:
            logger.warning("BM25: không có chunk nào để build index")
            return

        logger.info("BM25: bắt đầu build index cho %d chunks...", len(chunks))
        t0 = time.time()

        # Lưu chunk list để dùng khi trả kết quả
        self._chunks = chunks
        self._chunk_ids = [chunk.chunk_id for chunk in chunks]

        # Tokenize: dùng to_index_text() để thêm article_ref vào text
        corpus = [chunk.to_index_text().split() for chunk in chunks]

        self._bm25 = BM25Okapi(corpus)

        logger.info(
            "BM25: build xong trong %.2f giây — %d chunks indexed",
            time.time() - t0,
            len(chunks),
        )

    def save(self, path: str | Path = DEFAULT_BM25_FILE) -> None:
        """Lưu BM25 index xuống disk bằng pickle."""
        if self._bm25 is None:
            raise RuntimeError("BM25 index chưa được build. Gọi build() trước.")

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "bm25": self._bm25,
            "chunk_ids": self._chunk_ids,
            # Lưu text + metadata tối thiểu để reconstruct LegalChunk
            "chunk_data": [
                {
                    "chunk_id": c.chunk_id,
                    "doc_id": c.doc_id,
                    "text": c.text,
                    "article_ref": c.article_ref,
                    "char_len": c.char_len,
                    "chunk_index": c.chunk_index,
                    "metadata": c.metadata,
                }
                for c in self._chunks
            ],
        }
        with open(path, "wb") as f:
            pickle.dump(payload, f)
        logger.info("BM25: saved → %s (%.1fMB)", path, path.stat().st_size / 1024**2)

    @classmethod
    def load(cls, path: str | Path = DEFAULT_BM25_FILE) -> "BM25Index":
        """Load BM25 index đã lưu từ disk."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Không tìm thấy BM25 index: {path}")

        with open(path, "rb") as f:
            payload = pickle.load(f)

        instance = cls()
        instance._bm25 = payload["bm25"]
        instance._chunk_ids = payload["chunk_ids"]
        instance._chunks = [LegalChunk(**d) for d in payload["chunk_data"]]
        logger.info("BM25: loaded %d chunks từ %s", len(instance._chunk_ids), path)
        return instance

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self, query: str, top_k: int = 20
    ) -> List[Tuple[str, float]]:
        """
        Tìm kiếm theo từ khóa.

        Args:
            query: Câu hỏi hoặc từ khóa tìm kiếm
            top_k: Số kết quả trả về

        Returns:
            List of (chunk_id, score) — đã sắp xếp theo score giảm dần
        """
        if self._bm25 is None:
            raise RuntimeError("BM25 index chưa được load. Gọi build() hoặc load() trước.")

        tokenized_query = query.split()
        scores = self._bm25.get_scores(tokenized_query)

        # Lấy top_k index có score cao nhất
        top_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:top_k]

        return [
            (self._chunk_ids[i], float(scores[i]))
            for i in top_indices
            if scores[i] > 0  # bỏ qua kết quả score = 0 (không liên quan)
        ]

    def get_chunk(self, chunk_id: str) -> Optional[LegalChunk]:
        """Lấy LegalChunk theo chunk_id."""
        for chunk in self._chunks:
            if chunk.chunk_id == chunk_id:
                return chunk
        return None
