"""Cross-Encoder Reranker phục vụ tái xếp hạng văn bản pháp lý sau Hybrid Retrieval."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


class LegalReranker:
    """Bộ tái xếp hạng văn bản pháp lý hỗ trợ FlashRank (ONNX local), HTTP Endpoint và Fallback."""

    def __init__(self):
        self.settings = get_settings()
        self.config = self.settings.legal_assistant.reranker
        self.enabled = self.config.enabled
        self.engine = self.config.engine.lower()
        self.top_n = self.config.top_n

        # Khởi tạo FlashRank nếu có sẵn
        self._flashrank = None
        if self.enabled and self.engine == "flashrank":
            self._init_flashrank()

    def _init_flashrank(self) -> None:
        """Thử nạp FlashRank ONNX runtime."""
        try:
            from flashrank import Ranker
            self._flashrank = Ranker(model_name="ms-marco-MiniLM-L-12-v2")
            logger.info("[Reranker] Đã khởi tạo thành công FlashRank (Local ONNX CPU).")
        except ImportError:
            logger.warning("[Reranker] Chưa cài đặt thư viện 'flashrank'. Tự động kích hoạt cơ chế Smart Fallback.")
        except Exception as e:
            logger.warning(f"[Reranker] Khởi tạo FlashRank thất bại ({e}). Chuyển sang Smart Fallback.")

    async def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Tái xếp hạng danh sách documents theo query."""
        if not self.enabled or not documents:
            return documents[: (top_n or self.top_n)]

        n = top_n or self.top_n
        if len(documents) <= n:
            return documents

        # 1. Thử dùng FlashRank nếu sẵn sàng
        if self._flashrank is not None:
            try:
                from flashrank import RerankRequest

                passages = []
                for idx, doc in enumerate(documents):
                    title = doc.get("article_title") or doc.get("article") or ""
                    law = doc.get("law_name") or ""
                    # Lấy độ dài 4000 ký tự để bao quát được các Khoản phạt nặng ở giữa và cuối các Điều luật dài (như Điều 5, Điều 6)
                    text = f"{law} - {title}: {doc.get('content', '')[:4000]}"
                    passages.append({"id": idx, "text": text})

                req = RerankRequest(query=query, passages=passages)
                results = self._flashrank.rerank(req)

                reranked_docs = []
                for item in results[:n]:
                    orig_idx = item["id"]
                    doc_copy = dict(documents[orig_idx])
                    doc_copy["rerank_score"] = float(item["score"])
                    reranked_docs.append(doc_copy)

                logger.info(f"[Reranker - FlashRank] Đã tái xếp hạng từ {len(documents)} còn {len(reranked_docs)} docs.")
                return reranked_docs
            except Exception as e:
                logger.warning(f"[Reranker] Lỗi thực thi FlashRank ({e}), chuyển sang HTTP / Fallback.")

        # 2. Thử dùng HTTP Endpoint (TEI / vLLM / BGE Reranker)
        if self.config.base_url and self.engine in ("http", "vllm", "bge"):
            try:
                reranked = await self._rerank_via_http(query, documents, n)
                if reranked:
                    return reranked
            except Exception as e:
                logger.warning(f"[Reranker] Lỗi gọi HTTP Reranker endpoint ({e}), chuyển sang Smart Fallback.")

        # 3. Smart Lexical-Semantic Alignment Scorer (Graceful Fallback)
        return self._smart_fallback_rerank(query, documents, n)

    async def _rerank_via_http(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: int,
    ) -> Optional[List[Dict[str, Any]]]:
        """Gọi API rerank ngoài tương thích chuẩn /v1/rerank."""
        base_url = self.config.base_url.rstrip("/")
        endpoint = self.config.endpoint if self.config.endpoint.startswith("/") else f"/{self.config.endpoint}"
        url = f"{base_url}{endpoint}"

        doc_texts = [
            f"{d.get('law_name', '')} {d.get('article', '')} {d.get('article_title', '')}: {d.get('content', '')[:1200]}"
            for d in documents
        ]

        payload = {
            "model": self.config.model,
            "query": query,
            "documents": doc_texts,
            "top_n": top_n,
        }
        headers = {"Content-Type": "application/json"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results") or data
            if isinstance(results, list):
                reranked = []
                for item in results[:top_n]:
                    idx = item.get("index")
                    score = item.get("relevance_score") or item.get("score", 0.0)
                    if idx is not None and 0 <= idx < len(documents):
                        doc_copy = dict(documents[idx])
                        doc_copy["rerank_score"] = float(score)
                        reranked.append(doc_copy)
                if reranked:
                    logger.info(f"[Reranker - HTTP] Rerank thành công {len(reranked)} docs.")
                    return reranked

        return None

    def _smart_fallback_rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_n: int,
    ) -> List[Dict[str, Any]]:
        """Thuật toán Cross-Scoring thông minh dự phòng: Trọng số hóa cụm từ N-gram, tiêu đề, mật độ và tính chất điều luật."""
        q_lower = query.lower()
        q_tokens = [w for w in re.findall(r"\b[a-zà-ỹ0-9_]{2,}\b", q_lower) if w not in {"là", "bao", "nhiêu", "khi", "đang", "bị", "thì", "sao", "thế", "nào", "như", "các", "có", "cho", "của", "về", "trong"}]

        # Tạo danh sách cụm từ (bigrams) từ câu hỏi
        bigrams = [f"{q_tokens[i]} {q_tokens[i+1]}" for i in range(len(q_tokens) - 1)]

        is_penalty_query = any(k in q_lower for k in ["xử phạt", "bị phạt", "phạt bao nhiêu", "tội gì", "mức phạt", "phạt tù", "thế nào", "như thế nào", "tước bằng", "ở tù"])

        scored_docs = []
        for doc in documents:
            title = (doc.get("article_title") or "").lower()
            art = (doc.get("article") or "").lower()
            content = (doc.get("content") or "").lower()
            law = (doc.get("law_name") or "").lower()

            score = 0.0

            # 1. Khớp cụm từ chính xác N-gram trong Tiêu đề (Rất quan trọng)
            for bg in bigrams:
                if bg in title:
                    score += 15.0
                elif bg in content:
                    score += 4.0

            # 2. Mật độ từ khóa trong tiêu đề (ưu tiên tiêu đề súc tích, phản ánh đúng chủ đề)
            title_words = [w for w in re.findall(r"\b[a-zà-ỹ0-9_]{2,}\b", title)]
            if title_words:
                matched_title_tokens = sum(1 for t in q_tokens if t in title_words)
                density = matched_title_tokens / len(title_words)
                score += density * 12.0
                score += matched_title_tokens * 2.0

            # 3. Khớp từ khóa trong nội dung
            content_matches = sum(1 for t in q_tokens if t in content)
            score += content_matches * 1.0

            # 4. Ưu tiên điều luật định danh hành vi / tội phạm trực tiếp (Substantive law)
            if any(title.startswith(p) for p in ["tội ", "xử phạt hành vi", "xử phạt người"]):
                score += 8.0

            # 5. Khớp chính xác loại phương tiện tham gia giao thông
            if "xe máy" in q_lower or "mô tô" in q_lower:
                if "xe mô tô" in title or "xe gắn máy" in title:
                    score += 15.0
                elif "xe mô tô" in content or "xe gắn máy" in content:
                    score += 3.0
            if "ô tô" in q_lower:
                if "xe ô tô" in title:
                    score += 15.0
                elif "xe ô tô" in content:
                    score += 3.0

            # 6. Tinh chỉnh theo tính chất câu hỏi về chế tài xử phạt
            if is_penalty_query:
                # Giảm điểm các điều luật thuần về thẩm quyền/trang thiết bị nếu hỏi về mức phạt
                if any(title.startswith(p) for p in ["thẩm quyền", "nhiệm vụ", "trang bị", "phạm vi trách nhiệm"]):
                    score -= 6.0
                # Ưu tiên Bộ luật hình sự nếu hỏi về tội phạm/phạt tù và có khớp chủ đề
                if "hình sự" in law and any(bg in title for bg in bigrams):
                    score += 6.0

            # 7. Giảm điểm mạnh các điều luật thuần túy là kỹ thuật sửa đổi cơ học (diff bãi bỏ/thay thế cụm từ)
            if any(p in title for p in ["bổ sung, thay thế, bãi bỏ", "thay thế cụm từ", "sửa đổi, bổ sung một số điều của nghị định số"]):
                score -= 15.0

            # 8. Cộng dồn điểm RRF ban đầu
            score += doc.get("rrf_score", 0.0) * 5.0

            doc_copy = dict(doc)
            doc_copy["rerank_score"] = round(score, 4)
            scored_docs.append(doc_copy)

        # Sắp xếp lại theo điểm mới
        scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)
        logger.info(f"[Reranker - Smart Fallback] Đã tái xếp hạng {len(scored_docs)} docs.")
        return scored_docs[:top_n]
