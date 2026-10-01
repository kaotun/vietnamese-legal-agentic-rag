"""BM25 Lexical Search với cơ chế đệm (Disk Cache) theo hash dữ liệu (Phase 2)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple
from rank_bm25 import BM25Okapi

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache"


def tokenize_vietnamese(text: str) -> List[str]:
    """Tokenize văn bản tiếng Việt đơn giản và nhanh, tách theo từ và bỏ dấu câu."""
    text = text.lower()
    # Tách từ đơn giản qua regex giữ lại ký tự chữ tiếng Việt và số
    tokens = re.findall(r"\b[\w\d_]+\b", text)
    return [t for t in tokens if len(t) > 1]


class BM25KeywordStore:
    """Kho chỉ mục BM25 có khả năng lưu và tái sử dụng cache trên đĩa."""

    def __init__(self, cache_file: Path = CACHE_DIR / "bm25_index_cache.json"):
        self.cache_file = cache_file
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.bm25: BM25Okapi | None = None
        self.corpus_records: List[Dict[str, Any]] = []

    @staticmethod
    def compute_corpus_hash(records: List[Dict[str, Any]]) -> str:
        """Tính hash MD5 từ số lượng và các ID của corpus để xác thực cache."""
        hasher = hashlib.md5()
        hasher.update(str(len(records)).encode())
        for r in records[:50]:  # Hash mẫu đầu
            hasher.update(f"{r.get('id')}:{r.get('law_id')}".encode())
        for r in records[-50:]:  # Hash mẫu cuối
            hasher.update(f"{r.get('id')}:{r.get('law_id')}".encode())
        return hasher.hexdigest()

    def build_or_load(self, records: List[Dict[str, Any]]) -> None:
        """Tải từ cache nếu dữ liệu không đổi; nếu chưa có thì tính toán và lưu cache."""
        self.corpus_records = records
        current_hash = self.compute_corpus_hash(records)

        # Kiểm tra xem cache có sẵn và khớp hash không
        if self.cache_file.exists():
            try:
                logger.info(f"Đang kiểm tra BM25 cache tại: {self.cache_file}")
                cache_data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                if cache_data.get("corpus_hash") == current_hash and "tokenized_corpus" in cache_data:
                    tokenized_corpus = cache_data["tokenized_corpus"]
                    self.bm25 = BM25Okapi(tokenized_corpus)
                    logger.info(f"-> Nạp thành công BM25 từ cache ({len(tokenized_corpus)} văn bản).")
                    return
            except Exception as e:
                logger.warning(f"Không thể đọc BM25 cache, sẽ xây dựng lại: {e}")

        # Xây dựng mới với weighting ưu tiên Số hiệu Điều và Tiêu đề Điều luật
        logger.info(f"Đang xây dựng BM25 index cho {len(records)} văn bản luật...")
        tokenized_corpus: List[List[str]] = []
        for r in records:
            art = r.get("article", "")
            title = r.get("article_title", "")
            law = r.get("law_name", "")
            content = r.get("content", "")
            # Boost số hiệu điều và tiêu đề điều luật x2 để tăng recall khi truy vấn trực tiếp
            searchable_text = f"{art} {art} {title} {title} {law} {content}"
            tokens = tokenize_vietnamese(searchable_text)
            tokenized_corpus.append(tokens)

        self.bm25 = BM25Okapi(tokenized_corpus)
        logger.info("-> Xây dựng BM25 hoàn tất!")

        # Lưu cache
        try:
            cache_payload = {
                "corpus_hash": current_hash,
                "total_records": len(records),
                "tokenized_corpus": tokenized_corpus,
            }
            self.cache_file.write_text(json.dumps(cache_payload, ensure_ascii=False), encoding="utf-8")
            logger.info(f"-> Đã lưu BM25 cache vào: {self.cache_file}")
        except Exception as e:
            logger.warning(f"Lỗi khi lưu BM25 cache: {e}")

    def invalidate_cache(self) -> None:
        """Xóa file cache đĩa để buộc tính toán lại chỉ mục ở lần khởi tạo kế tiếp."""
        try:
            if self.cache_file.exists():
                self.cache_file.unlink()
                logger.info(f"[BM25] Đã xóa cache đĩa: {self.cache_file}")
        except Exception as e:
            logger.warning(f"[BM25] Không thể xóa file cache: {e}")

    def reload(self, records: List[Dict[str, Any]]) -> None:
        """Nạp lại chỉ mục BM25 trực tiếp trên RAM khi có dữ liệu mới."""
        self.invalidate_cache()
        self.build_or_load(records)


    def search(self, query: str, top_k: int = 20) -> List[Tuple[Dict[str, Any], float]]:
        """Tìm kiếm các Điều luật liên quan nhất theo BM25."""
        if not self.bm25 or not self.corpus_records:
            return []

        tokens = tokenize_vietnamese(query)
        if not tokens:
            return []

        scores = self.bm25.get_scores(tokens)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]

        results = []
        for idx in ranked_indices:
            score = float(scores[idx])
            if score > 0:  # Chỉ lấy kết quả có khớp từ khóa
                results.append((self.corpus_records[idx], score))
        return results
