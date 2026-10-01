"""Node sinh câu trả lời pháp lý chuẩn cấu trúc 4 phần bằng LLM (Generation Node)."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple
from src.agent.llm_client import LLMClient
from src.agent.state import LegalAgentState
from src.agent.prompt_builder import (
    LegalPromptBuilder,
    build_generation_prompt,
    clean_all_repetition,
)

logger = logging.getLogger(__name__)


async def generate_node(state: LegalAgentState, llm: LLMClient) -> Dict[str, Any]:
    """Node tổng hợp tri thức pháp luật và sinh câu trả lời có cấu trúc 4 phần bằng LLM."""
    query = state["query"]
    standalone_query = state.get("standalone_query") or query
    history = list(state.get("history") or [])
    retrieved_docs = state.get("retrieved_docs") or []
    correction_feedback = state.get("correction_feedback")

    logger.info(f"[GenerateNode] Bắt đầu sinh câu trả lời cho: '{query}' (Docs: {len(retrieved_docs)})")

    if not retrieved_docs:
        fallback_answer = (
            "### 1. Kết luận\nHiện tại hệ thống chưa tìm thấy văn bản quy phạm pháp luật trực tiếp phù hợp trong cơ sở dữ liệu để giải đáp câu hỏi của bạn.\n\n"
            "### 2. Căn cứ pháp lý\nChưa có căn cứ trích dẫn trực tiếp.\n\n"
            "### 3. Chi tiết áp dụng\nVui lòng cung cấp thêm từ khóa hoặc diễn đạt chi tiết hơn để được tra cứu chính xác.\n\n"
            "### 4. Lưu ý thực tiễn\nBạn nên tham khảo ý kiến luật sư hoặc cơ quan có thẩm quyền đối với các vụ việc cụ thể."
        )
        updated_history = list(history)
        updated_history.append({"role": "user", "content": query})
        updated_history.append({"role": "assistant", "content": fallback_answer})
        return {
            "answer": fallback_answer,
            "citations": [],
            "retrieved_docs": [],
            "history": updated_history,
            "guard_status": "warning",
            "correction_feedback": None,
        }

    # 1. Trích xuất prompt và citations thống nhất từ LegalPromptBuilder
    messages, citations, enriched_docs = build_generation_prompt(state)

    # 2. Sinh lời giải qua LLM với error handling an toàn
    try:
        raw_answer = await llm.generate(messages)
    except Exception as e:
        logger.error(f"[GenerateNode] Lỗi khi gọi LLM: {e}")
        error_answer = (
            "### 1. Kết luận\nHiện tại hệ thống chưa thể kết nối tới mô hình AI (Model Serving) để xử lý câu hỏi của bạn.\n\n"
            "### 2. Căn cứ pháp lý\n" + ("\n".join(f"- {c}" for c in citations[:2]) if citations else "Căn cứ từ tài liệu tra cứu.") + "\n\n"
            "### 3. Phân tích & Chi tiết áp dụng\nVui lòng kiểm tra lại dịch vụ Ollama / vLLM hoặc liên hệ quản trị viên.\n\n"
            "### 4. Hướng dẫn & Lưu ý thực tiễn\nBạn có thể thử gửi lại yêu cầu sau ít phút."
        )
        updated_history = list(history)
        updated_history.append({"role": "user", "content": query})
        updated_history.append({"role": "assistant", "content": error_answer})
        return {
            "answer": error_answer,
            "citations": citations,
            "retrieved_docs": enriched_docs,
            "history": updated_history,
            "guard_status": "warning",
            "followup_questions": [],
            "correction_feedback": None,
        }

    # 3. Phân tách câu hỏi gợi ý và làm sạch câu trả lời
    clean_answer, followup_questions = LegalPromptBuilder.extract_followup_and_clean_answer(raw_answer)

    clean_answer = re.sub(
        r'(\n\s*-\s*|\n\s*)\**\[\s*(?:TÀI\s*LIỆU|NGUỒN(?:\s*PHÁP\s*LUẬT)?)\s*\d+\s*\]\**\s*:\s*',
        r'\1',
        clean_answer,
        flags=re.IGNORECASE
    )
    clean_answer = clean_all_repetition(clean_answer)

    # Bổ sung số Điều cụ thể vào Căn cứ pháp lý nếu cần
    if citations and "### 2. Căn cứ pháp lý" in clean_answer:
        def _enrich_legal_basis(m):
            header = m.group(1)
            body = m.group(2)
            if "Điều" not in body:
                primary_cit = citations[0].split(" - ")[0].strip()
                law_title = citations[0].split(" - ")[1].strip() if " - " in citations[0] else ""
                enriched_line = f"- {primary_cit} {law_title}".strip()
                return f"{header}{enriched_line}\n\n"
            return m.group(0)

        clean_answer = re.sub(
            r'(### 2\. Căn cứ pháp lý\s*\n)([\s\S]*?)(?=\n###|\Z)',
            _enrich_legal_basis,
            clean_answer,
            count=1
        )

    if len(followup_questions) < 2:
        topic = standalone_query.replace("Quy định về ", "").replace("Xử phạt hành vi ", "")
        followup_questions = [
            f"Thủ tục, giấy tờ cần chuẩn bị đối với {topic[:40]}?",
            f"Mức chế tài hoặc quyền lợi cụ thể liên quan đến {topic[:35]}?",
            f"Thời hạn giải quyết và cơ quan có thẩm quyền xử lý?",
        ]

    # Cập nhật lịch sử
    updated_history = list(history)
    updated_history.append({"role": "user", "content": query})
    updated_history.append({"role": "assistant", "content": clean_answer})

    return {
        "answer": clean_answer,
        "citations": citations,
        "retrieved_docs": enriched_docs,
        "history": updated_history,
        "followup_questions": followup_questions[:3],
        "correction_feedback": None,  # Đã tiêu thụ feedback
    }
