"""Node phản hồi tự sửa sai khi phát hiện trích dẫn ảo (Self-Correction Node)."""
from __future__ import annotations

import logging
from typing import Any, Dict
from src.agent.state import LegalAgentState

logger = logging.getLogger(__name__)


async def self_correct_node(state: LegalAgentState) -> Dict[str, Any]:
    """Tạo phản hồi nhắc nhở LLM loại bỏ các điều luật ảo giác và sinh lại câu trả lời (Self-RAG Loop)."""
    hallucinated = state.get("hallucinated_articles") or []
    retry_count = state.get("retry_count", 0) + 1

    logger.info(f"[SelfCorrectNode] Kích hoạt Self-RAG Loop (Lần {retry_count}). Điều luật ảo giác: {hallucinated}")

    hallucinated_str = ", ".join(sorted(hallucinated)) if hallucinated else "không xác định"
    feedback = (
        f"[CẢNH BÁO KIỂM ĐỊNH TRÍCH DẪN - YÊU CẦU ĐIỀU CHỈNH LẦN {retry_count}]:\n"
        f"- Câu trả lời trước đây của bạn có viện dẫn các Điều luật KHÔNG TỒN TẠI trong tài liệu được cung cấp: {hallucinated_str}.\n"
        f"- YÊU CẦU BẮT BUỘC: Viết lại toàn bộ câu trả lời, TUYỆT ĐỐI CHỈ sử dụng các Điều luật có trong [NGỮ CẢNH PHÁP LÝ] ở trên. Không tự ý bịa đặt hoặc suy diễn bất kỳ số Điều nào khác!"
    )

    return {
        "correction_feedback": feedback,
        "retry_count": retry_count,
        "guard_status": "regenerating",
    }
