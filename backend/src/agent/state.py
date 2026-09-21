"""Định nghĩa trạng thái hoạt động (State) của LangGraph Legal Agent (Phase 4)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional
from typing_extensions import TypedDict


class LegalAgentState(TypedDict):
    """Trạng thái luân chuyển giữa các node trong Agent StateGraph."""
    query: str
    session_id: Optional[str]
    history: List[Dict[str, str]]  # Danh sách [{"role": "user"|"assistant", "content": "..."}]
    standalone_query: Optional[str]  # Query đã giải quyết quy chiếu và tỉnh lược
    intent: str  # "legal_query" | "smalltalk" | "out_of_scope"
    retrieved_docs: List[Dict[str, Any]]
    answer: str
    citations: List[str]
    guard_status: str  # "passed" | "warning" | "regenerated"
    followup_questions: Optional[List[str]]  # 3 câu hỏi gợi ý đào sâu theo ngữ cảnh
    is_multi_violation: Optional[bool]  # Cờ nhận diện câu hỏi chứa nhiều hành vi vi phạm
    sub_queries: Optional[List[str]]  # Danh sách các truy vấn con sau khi phân rã
    hypothetical_passage: Optional[str]  # Đoạn văn bản luật giả định (HyDE)
    docs_grade: Optional[str]  # Đánh giá tài liệu: "relevant" | "irrelevant"
    retry_count: int  # Đếm số lần lặp phản hồi (tối đa 2 để tránh lặp vô hạn)
    hallucinated_articles: Optional[List[str]]  # Danh sách điều luật bị ảo giác phát hiện bởi Guard
    correction_feedback: Optional[str]  # Hướng dẫn điều chỉnh gửi cho LLM ở vòng lặp Self-Correction
    error: Optional[str]
