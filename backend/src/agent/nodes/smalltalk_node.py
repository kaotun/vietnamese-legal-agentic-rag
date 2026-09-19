"""Node xử lý xã giao và chào hỏi không cần tốn chi phí truy hồi."""
from __future__ import annotations

from src.agent.llm_client import LLMClient
from src.agent.state import LegalAgentState


async def smalltalk_node(state: LegalAgentState, llm: LLMClient | None = None) -> LegalAgentState:
    """Trả lời câu hỏi chào hỏi/xã giao thân thiện và duy trì lịch sử hội thoại."""
    default_answers = {
        "xin chào": "Xin chào bạn! Tôi là Trợ lý Pháp luật Việt Nam. Tôi có thể hỗ trợ bạn tra cứu và giải đáp các quy định pháp luật. Bạn cần hỗ trợ vấn đề gì hôm nay?",
        "cảm ơn": "Rất vui được hỗ trợ bạn! Nếu có thêm thắc mắc pháp lý nào khác, bạn cứ đặt câu hỏi nhé.",
    }
    q = state["query"].strip().lower()
    answer = None
    for k, v in default_answers.items():
        if k in q:
            answer = v
            break

    if not answer and llm:
        system_prompt = "Bạn là Trợ lý Pháp luật Việt Nam lịch sự và tận tâm. Hãy chào hỏi hoặc trả lời xã giao ngắn gọn, sau đó mời người dùng đặt câu hỏi về pháp luật."
        answer = await llm.generate([
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": state["query"]}
        ])

    if not answer:
        answer = "Xin chào! Tôi là Trợ lý Pháp luật Việt Nam. Bạn có câu hỏi nào về pháp luật cần tôi giải đáp không?"

    history = list(state.get("history") or [])
    history.append({"role": "user", "content": state["query"]})
    history.append({"role": "assistant", "content": answer})

    return {
        **state,
        "answer": answer,
        "history": history,
        "guard_status": "passed",
        "followup_questions": [
            "Mức phạt xe máy và ô tô vượt đèn đỏ mới nhất?",
            "Thời gian thử việc tối đa theo Bộ luật Lao động 2019?",
            "Thủ tục đăng ký kết hôn cần chuẩn bị những giấy tờ gì?",
        ],
    }
