"""Node phân loại ý định (Intent Router) chuẩn hóa theo nguyên lý tổng quát (Generalizable Production Routing)."""
from __future__ import annotations

import re
from typing import Literal
from src.agent.llm_client import LLMClient
from src.agent.state import LegalAgentState

IntentType = Literal["legal_query", "smalltalk", "out_of_scope"]

# 1. Fast-Path Regex cho các câu chào hỏi / giao tiếp xã giao phổ biến (< 1ms)
SMALLTALK_FAST_REGEX = re.compile(
    r"^(chào|xin chào|hello|hi|hey|alo|bạn là ai|bạn tên gì|cảm ơn|cám ơn|thanks|tks|tạm biệt|bye)\b",
    re.IGNORECASE
)

# 2. Nhận diện các câu hỏi phụ thuộc / tỉnh lược ngữ cảnh (Elliptical / Follow-up queries)
# Các câu bắt đầu bằng từ nối hoặc câu cụt cần tham chiếu chủ thể từ lượt hội thoại trước
ELLIPTICAL_FOLLOWUP_REGEX = re.compile(
    r"^(thế còn|còn|vậy|nếu|vậy thì|thế thì|có bị|bị phạt|mức phạt|bao nhiêu|như thế nào|thế nào|ở đâu|khi nào|tại sao|được không|không)\b",
    re.IGNORECASE
)

# 3. Prompt phân loại theo Bản chất Pháp lý Trừu tượng (First-Principles), không liệt kê tội danh cụ thể
ROUTER_SYSTEM_PROMPT = """Bạn là Bộ phân loại ý định (Intent Classifier) cho Hệ thống Tư vấn Pháp luật Việt Nam.
Nhiệm vụ: Phân loại câu hỏi của người dùng vào đúng 1 trong 3 nhãn sau:

1. 'legal_query':
   - Mọi câu hỏi liên quan đến quy định pháp luật, quyền, nghĩa vụ, thủ tục, trách nhiệm pháp lý, vi phạm hoặc chế tài xử lý của cá nhân/tổ chức (thuộc bất kỳ lĩnh vực pháp lý nào: hình sự, dân sự, hành chính, giao thông, lao động, kinh doanh, đất đai, hôn nhân gia đình, thuế, tài chính...).
   - Các câu hỏi nối tiếp để làm rõ hoặc so sánh tình huống pháp lý trong hội thoại.

2. 'smalltalk':
   - Lời chào hỏi, tạm biệt, cảm ơn hoặc giao tiếp xã giao với trợ lý.

3. 'out_of_scope':
   - Câu hỏi kiến thức đời sống thuần túy hoàn toàn không liên quan đến pháp luật (nấu ăn, thể thao, giải toán, khoa học tự nhiên, thời tiết, giải trí, lập trình...).

Quy tắc bắt buộc:
- Trả về DUY NHẤT 1 nhãn: legal_query, smalltalk hoặc out_of_scope.
- Không kèm bất kỳ giải thích nào khác."""


def is_elliptical_query(query: str) -> bool:
    """Kiểm tra câu hỏi có phải dạng tỉnh lược / phụ thuộc ngữ cảnh trước hay không."""
    q = query.strip()
    words = q.split()
    return len(words) <= 4 or bool(ELLIPTICAL_FOLLOWUP_REGEX.search(q))


def parse_intent_label(raw_resp: str) -> IntentType:
    """Trích xuất nhãn phân loại chuẩn mực từ phản hồi của LLM, hỗ trợ Fallback an toàn."""
    text = raw_resp.strip().lower()
    matches = re.findall(r"\b(legal_query|smalltalk|out_of_scope)\b", text)
    if matches:
        return matches[0]
    return "legal_query"


async def intent_router_node(state: LegalAgentState, llm: LLMClient | None = None) -> LegalAgentState:
    """Phân loại ý định kết hợp Fast-Path và Context-Isolated Semantic Routing."""
    query = state["query"].strip()
    history = state.get("history") or []

    # TIER 1: Fast-Path cho Smalltalk thuần túy (Zero-latency)
    # Chỉ kích hoạt khi câu chào ngắn (<= 4 từ) hoặc câu xã giao không chứa vế hỏi/nghi vấn đằng sau.
    # Tránh trường hợp người dùng lịch sự: "Chào bạn, cho tôi hỏi vượt đèn đỏ phạt bao nhiêu?" bị biến thành smalltalk.
    words = query.split()
    has_question_or_substance = (
        len(words) > 4
        or "?" in query
        or bool(re.search(r"\b(hỏi|cho hỏi|muốn hỏi|phạt|luật|điều|khoản|tội|quy định|thủ tục|mức|bao nhiêu|như thế nào|thế nào|sao|được không|có được|bị gì)\b", query, re.I))
    )
    if SMALLTALK_FAST_REGEX.search(query) and not has_question_or_substance:
        return {**state, "intent": "smalltalk"}


    # TIER 2: Semantic Routing qua LLM
    if llm:
        try:
            # Ngăn chặn ô nhiễm ngữ cảnh (Context Pollution):
            # Chỉ nạp ngữ cảnh câu hỏi trước khi câu hiện tại là câu hỏi nối tiếp/tỉnh lược.
            # Nếu câu hỏi đã đầy đủ chủ vị, phân loại độc lập để tránh bị lệch chủ đề.
            is_followup = is_elliptical_query(query)
            last_user_query = None
            if history:
                last_user_query = next((m.get("content") for m in reversed(history) if m.get("role") == "user"), None)

            if is_followup and last_user_query and last_user_query != query:
                user_prompt = f"Ngữ cảnh câu hỏi trước: \"{last_user_query}\"\nCâu hỏi nối tiếp hiện tại: \"{query}\"\nNhãn:"
            else:
                user_prompt = f"Câu hỏi: \"{query}\"\nNhãn:"

            resp = await llm.generate([
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ], temperature=0.0)

            intent = parse_intent_label(resp)
            return {**state, "intent": intent}
        except Exception:
            pass

    # TIER 3: Optimistic Fallback (Mặc định cho vào RAG pipeline của hệ thống pháp luật)
    return {**state, "intent": "legal_query"}
