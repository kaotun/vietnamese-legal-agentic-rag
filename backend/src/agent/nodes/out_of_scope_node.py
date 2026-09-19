"""Node từ chối lịch sự khi câu hỏi nằm ngoài phạm vi pháp luật Việt Nam."""
from __future__ import annotations

from src.agent.state import LegalAgentState


async def out_of_scope_node(state: LegalAgentState) -> LegalAgentState:
    """Từ chối lịch sự các câu hỏi ngoài phạm vi nghiệp vụ và duy trì lịch sử hội thoại."""
    refusal_msg = (
        "Xin lỗi bạn, tôi là Trợ lý Pháp luật Việt Nam và chỉ được thiết kế để giải đáp, "
        "tra cứu các quy định, thủ tục pháp lý của nước Cộng hòa Xã hội Chủ nghĩa Việt Nam. "
        "Câu hỏi của bạn hiện nằm ngoài phạm vi chuyên môn này. "
        "Vui lòng đặt câu hỏi liên quan đến pháp luật để được hỗ trợ tốt nhất."
    )
    history = list(state.get("history") or [])
    history.append({"role": "user", "content": state["query"]})
    history.append({"role": "assistant", "content": refusal_msg})

    return {
        **state,
        "answer": refusal_msg,
        "history": history,
        "guard_status": "passed",
        "followup_questions": [
            "Mức phạt vi phạm nồng độ cồn khi lái xe?",
            "Thủ tục đăng ký kết hôn cần những giấy tờ gì?",
            "Quy định về bồi thường thu hồi đất ở?",
        ],
    }
