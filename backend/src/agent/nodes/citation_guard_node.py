"""Node phòng vệ trích dẫn (Citation Guard) chạy runtime trước khi gửi câu trả lời."""
from __future__ import annotations

import re
from typing import List, Set
from src.agent.state import LegalAgentState


def extract_mentioned_articles(text: str) -> Set[str]:
    """Trích xuất các số Điều luật được nhắc tới trong văn bản (ví dụ: 'Điều 53', 'Điều 146')."""
    pattern = re.compile(r"Điều\s+(\d+)", re.IGNORECASE)
    matches = pattern.findall(text)
    return {f"Điều {m}" for m in matches}


async def citation_guard_node(state: LegalAgentState) -> LegalAgentState:
    """Đối chiếu rule-based các Điều luật trích dẫn với context đã truy hồi."""
    # Bỏ qua nếu là nhánh smalltalk hoặc out_of_scope
    if state.get("intent") in ["smalltalk", "out_of_scope"]:
        return {**state, "guard_status": "passed"}

    answer = state.get("answer", "")
    retrieved_docs = state.get("retrieved_docs", [])

    # Tập hợp các Điều luật có trong context thực tế (cả tiêu đề và nội dung bên trong các văn bản)
    context_articles: Set[str] = set()
    for doc in retrieved_docs:
        art_field = doc.get("article", "")
        # Trích xuất số điều từ "Điều 53" hoặc "53"
        match = re.search(r"\d+", art_field)
        if match:
            context_articles.add(f"Điều {match.group()}")

        # Bao gồm cả các điều luật được quy định hoặc viện dẫn chéo trong nội dung văn bản
        doc_body = (doc.get("content", "") or "") + " " + (doc.get("focused_content", "") or "")
        for m in re.findall(r"Điều\s+(\d+)", doc_body, re.IGNORECASE):
            context_articles.add(f"Điều {m}")

    # Tập hợp các Điều luật LLM nêu trong câu trả lời
    mentioned_articles = extract_mentioned_articles(answer)

    # Danh mục các Điều luật nguyên tắc xử lý vi phạm hành chính, trách nhiệm hình sự cơ bản
    GENERAL_PROCEDURAL_ARTICLES = {
        "Điều 3", "Điều 4", "Điều 8", "Điều 12", "Điều 28", "Điều 29",
        "Điều 51", "Điều 52", "Điều 67", "Điều 68", "Điều 79"
    }

    # Tìm các Điều luật bị LLM "bịa" thêm ngoài context
    hallucinated_articles = mentioned_articles - context_articles - GENERAL_PROCEDURAL_ARTICLES

    if hallucinated_articles:
        retry_count = state.get("retry_count", 0)
        # Nếu còn lượt retry (tối đa 2 lần), kích hoạt vòng lặp Self-Correction
        if retry_count < 2:
            return {
                **state,
                "guard_status": "retry",
                "hallucinated_articles": list(hallucinated_articles),
            }

        # Nếu đã hết lượt retry mà vẫn còn lệch, gắn nhãn cảnh báo an toàn
        warning_header = (
            f"> [!WARNING]\n"
            f"> **Lưu ý kiểm tra trích dẫn**: Hệ thống phát hiện câu trả lời có viện dẫn "
            f"**{', '.join(sorted(hallucinated_articles))}** nhưng điều khoản này không nằm trong ngữ cảnh trích lục trực tiếp từ cơ sở dữ liệu đã truy hồi. Vui lòng đối chiếu lại văn bản gốc.\n\n"
        )
        guarded_answer = warning_header + answer
        history = list(state.get("history") or [])
        if history and history[-1].get("role") == "assistant":
            history[-1]["content"] = guarded_answer
        return {
            **state,
            "answer": guarded_answer,
            "history": history,
            "guard_status": "warning",
            "hallucinated_articles": list(hallucinated_articles),
        }

    return {
        **state,
        "guard_status": "passed",
        "hallucinated_articles": [],
    }
