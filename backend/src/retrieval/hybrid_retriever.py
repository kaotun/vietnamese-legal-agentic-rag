"""Hybrid Retriever kết hợp BM25 và Vector Search bằng Reciprocal Rank Fusion (RRF)."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import asyncpg

from src.config import get_settings
from src.retrieval.keyword_store import BM25KeywordStore
from src.retrieval.vector_client import EmbeddingsClient

from src.retrieval.reranker import LegalReranker

logger = logging.getLogger(__name__)


class HybridLegalRetriever:
    """Bộ truy hồi hỗn hợp kết hợp ngữ nghĩa, từ khóa và Reranker cho hệ thống pháp luật."""

    def __init__(self, reranker: Optional[LegalReranker] = None):
        self.settings = get_settings()
        self.keyword_store = BM25KeywordStore()
        self.vector_client = EmbeddingsClient()
        self.reranker = reranker or LegalReranker()
        self.records: List[Dict[str, Any]] = []
        self._is_ready = False

    async def initialize(self) -> None:
        """Đọc records từ PostgreSQL và dựng/nạp BM25 cache."""
        if self._is_ready:
            return

        db_url = self.settings.legal_assistant.postgres.database_url
        table_name = "legal_knowledge_records"
        logger.info(f"Kết nối tới PostgreSQL để đọc văn bản luật: {db_url}")

        try:
            conn = await asyncpg.connect(db_url)
            rows = await conn.fetch(f"SELECT id, law_id, law_name, doc_type, article, article_title, content, author FROM {table_name} ORDER BY id ASC;")
            await conn.close()

            self.records = [dict(r) for r in rows]
            logger.info(f"Đã đọc {len(self.records)} Điều luật từ cơ sở dữ liệu.")

            # Nạp hoặc xây dựng BM25 index
            self.keyword_store.build_or_load(self.records)
            self._is_ready = True
            logger.info("Hybrid Retriever đã sẵn sàng phục vụ!")
        except Exception as e:
            logger.error(f"Lỗi khi khởi tạo Hybrid Retriever: {e}")
            raise

    def rrf_fusion(
        self,
        bm25_results: List[Dict[str, Any]],
        vector_results: List[Dict[str, Any]],
        top_k: int = 5,
        rrf_k: int = 60,
    ) -> List[Dict[str, Any]]:
        """Thuật toán Reciprocal Rank Fusion kết hợp xếp hạng từ 2 nguồn."""
        scores: Dict[int, float] = {}
        record_map: Dict[int, Dict[str, Any]] = {}

        # 1. Tính điểm từ BM25
        for rank, item in enumerate(bm25_results):
            rec_id = item["id"]
            scores[rec_id] = scores.get(rec_id, 0.0) + (1.0 / (rrf_k + rank + 1))
            record_map[rec_id] = item

        # 2. Tính điểm từ Vector (nếu có)
        for rank, item in enumerate(vector_results):
            rec_id = item["id"]
            scores[rec_id] = scores.get(rec_id, 0.0) + (1.0 / (rrf_k + rank + 1))
            record_map[rec_id] = item

        # Sắp xếp theo điểm RRF giảm dần
        sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)[:top_k]
        fused_items = []
        for rid in sorted_ids:
            item = dict(record_map[rid])
            item["rrf_score"] = scores[rid]
            fused_items.append(item)

        return fused_items

    async def search(
        self,
        query: str,
        top_k: int = 5,
        hypothetical_passage: Optional[str] = None,
        apply_rerank: bool = True,
    ) -> List[Dict[str, Any]]:
        """Truy hồi các Điều luật phù hợp nhất kết hợp BM25, HyDE và Cross-Encoder Reranker."""
        if not self._is_ready:
            await self.initialize()

        # Số lượng ứng viên sơ bộ cần lấy trước khi rerank (lấy rộng ít nhất 30-35 docs để không bỏ sót các Điều luật dài)
        candidate_pool_size = max(top_k * 5, 35, self.settings.legal_assistant.retrieval.top_k)

        # 1. Tìm theo BM25 bằng câu hỏi gốc/mở rộng
        bm25_matches = self.keyword_store.search(query, top_k=candidate_pool_size)
        bm25_candidates = [item for item, _ in bm25_matches]

        # 2. Nếu có passage giả định (HyDE), tìm thêm BM25 trên passage để tăng độ phủ thuật ngữ
        if hypothetical_passage and hypothetical_passage != query:
            hyde_bm25_matches = self.keyword_store.search(hypothetical_passage, top_k=candidate_pool_size // 2)
            hyde_candidates = [item for item, _ in hyde_bm25_matches]
            # Hợp nhất danh sách ứng viên qua RRF nội bộ
            bm25_candidates = self.rrf_fusion(bm25_candidates, hyde_candidates, top_k=candidate_pool_size)

        # 3. Tìm theo Vector Embedding (nếu endpoint khả dụng)
        vector_candidates: List[Dict[str, Any]] = []
        try:
            target_embed_text = hypothetical_passage if hypothetical_passage else query
            query_vector = await self.vector_client.embed_query(target_embed_text)
            if query_vector:
                # Vector search logic nếu có pgvector index
                pass
        except Exception as e:
            logger.warning(f"[Retrieval] Vector search lỗi hoặc không khả dụng: {e}")

        # 4. Hợp nhất RRF
        if vector_candidates:
            fused_candidates = self.rrf_fusion(bm25_candidates, vector_candidates, top_k=candidate_pool_size)
        else:
            fused_candidates = bm25_candidates[:candidate_pool_size]

        # 5. Tái xếp hạng bằng Cross-Encoder Reranker
        if apply_rerank and self.reranker and self.reranker.enabled:
            reranked = await self.reranker.rerank(query=query, documents=fused_candidates, top_n=top_k)
            return reranked

        return fused_candidates[:top_k]

    async def search_multi_queries(
        self,
        sub_queries: List[str],
        top_k_per_query: int = 3,
        total_top_k: int = 8,
        apply_rerank: bool = True,
    ) -> List[Dict[str, Any]]:
        """Truy hồi song song cho nhiều sub-queries và hợp nhất (deduplicate & balance)."""
        if not self._is_ready:
            await self.initialize()

        if not sub_queries:
            return []

        import asyncio
        search_tasks = [
            self.search(query=sq, top_k=top_k_per_query, apply_rerank=apply_rerank)
            for sq in sub_queries
        ]
        results_list = await asyncio.gather(*search_tasks, return_exceptions=True)

        merged_docs: List[Dict[str, Any]] = []
        seen_keys = set()

        max_len = max((len(r) for r in results_list if isinstance(r, list)), default=0)
        for i in range(max_len):
            for r in results_list:
                if isinstance(r, list) and i < len(r):
                    doc = r[i]
                    key = (doc.get("law_name"), doc.get("article"))
                    if key not in seen_keys:
                        seen_keys.add(key)
                        merged_docs.append(doc)
                        if len(merged_docs) >= total_top_k:
                            return merged_docs

        return merged_docs[:total_top_k]
