"""Node đánh giá độ liên quan của tài liệu truy hồi (Document Relevance Grader Node)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict
from src.agent.state import LegalAgentState

logger = logging.getLogger(__name__)

COMMON_LEGAL_STOPWORDS = {
    "phạt", "tiền", "đồng", "đối", "với", "người", "điều", "khiển", "hành", "vi",
    "sau", "đây", "theo", "quy", "định", "tại", "khoản", "luật", "này", "khi",
    "tham", "gia", "thực", "hiện", "trong", "trường", "hợp", "hoặc", "không",
    "các", "loại", "cho", "của", "được", "bao", "nhiêu", "như", "thế", "nào",
    "một", "những", "có", "thể", "bị", "bởi", "về", "và", "là", "đã", "sẽ",
}


async def grade_documents_node(state: LegalAgentState) -> Dict[str, Any]:
    """Tự động đánh giá xem tập tài liệu đã truy hồi có đủ độ liên quan để giải đáp câu hỏi không."""
    retrieved_docs = state.get("retrieved_docs", [])
    query = state.get("standalone_query") or state["query"]
    retry_count = state.get("retry_count", 0)

    # 1. Nếu không tìm thấy tài liệu nào
    if not retrieved_docs:
        logger.warning(f"[GradeDocsNode] Không tìm thấy tài liệu nào cho query: '{query}'. Đánh giá: IRRELEVANT")
        return {"docs_grade": "irrelevant"}

    # 2. Kiểm tra độ trùng khớp từ khóa thực tế và điểm số reranker
    query_words = [
        w for w in re.findall(r"\b[\w\d_]+\b", query.lower())
        if len(w) > 2 and w not in COMMON_LEGAL_STOPWORDS
    ]

    top_doc = retrieved_docs[0]
    top_content = (top_doc.get("content", "") + " " + top_doc.get("article_title", "")).lower()
    
    # Đếm số từ khóa quan trọng có trong tài liệu top 1
    matched_keywords = sum(1 for w in query_words if w in top_content)
    match_ratio = matched_keywords / max(len(query_words), 1)

    # Kiểm tra điểm rerank (nếu có)
    rerank_score = top_doc.get("rerank_score")

    logger.info(f"[GradeDocsNode] Top 1: '{top_doc.get('article')}' (Khớp {matched_keywords}/{len(query_words)} từ khóa, score={rerank_score})")

    # Nếu tài liệu có từ khóa khớp hoặc điểm số đạt ngưỡng
    if match_ratio >= 0.25 or (rerank_score is not None and rerank_score > 0.15) or len(query_words) <= 1:
        grade = "relevant"
    else:
        # Nếu điểm quá thấp và vẫn còn ngân sách retry
        if retry_count < 2:
            grade = "irrelevant"
        else:
            grade = "relevant"  # Hết lượt retry thì cố gắng dùng tài liệu hiện có

    logger.info(f"[GradeDocsNode] Kết quả thẩm định tài liệu: {grade.upper()} (Lần thử {retry_count + 1})")
    return {
        "docs_grade": grade,
    }
