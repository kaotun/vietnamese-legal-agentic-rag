"""Module viết lại truy vấn (Query Rewriting) chuẩn hóa thuật ngữ pháp lý bằng LLM."""
from __future__ import annotations

import logging
import re
from typing import List, Dict, Optional

from src.agent.llm_client import LLMClient
from src.core.config import get_settings

logger = logging.getLogger(__name__)

REWRITE_SYSTEM_PROMPT = """Bạn là chuyên gia chuẩn hóa truy vấn tra cứu pháp luật Việt Nam.
Nhiệm vụ: Viết lại câu hỏi đời thường của công dân thành một truy vấn tra cứu ngắn gọn, chuẩn xác thuật ngữ pháp lý chính thống để phục vụ tìm kiếm điều luật.

Quy tắc bắt buộc:
1. Giữ nguyên toàn bộ dữ kiện quan trọng: số tiền, thời hạn, hành vi, loại phương tiện, loại hợp đồng, đối tượng áp dụng.
2. Chuẩn hóa từ lóng, khẩu ngữ thành thuật ngữ pháp quy chính xác:
   - Các hành vi vi phạm giao thông thông thường (đèn đỏ, ngược chiều, mũ bảo hiểm, rượu bia...) mặc định thuộc "giao thông đường bộ" (trừ khi câu hỏi nói rõ đường sắt hoặc đường thủy).
   - "sa thải / đuổi việc" -> "đơn phương chấm dứt hợp đồng lao động / kỷ luật sa thải"
   - "kẹp 3 / kẹp ba / chở 3" -> "chở quá số người quy định xe mô tô xe gắn máy"
   - "vượt đèn đỏ / vượt đèn" -> "xử phạt hành vi không chấp hành hiệu lệnh của đèn tín hiệu giao thông đường bộ đối với xe mô tô xe gắn máy xe ô tô"
   - "sổ đỏ / sổ hồng" -> "giấy chứng nhận quyền sử dụng đất và tài sản gắn liền với đất"
   - "say xỉn / uống rượu bia lái xe" -> "vi phạm nồng độ cồn khi điều khiển phương tiện giao thông đường bộ"
   - "điện thoại khi lái xe" -> "sử dụng điện thoại di động khi đang điều khiển phương tiện giao thông đường bộ"
3. KHÔNG tự ý bịa đặt số Điều, số Khoản hoặc mã văn bản luật cụ thể nếu câu hỏi không nêu.
4. Chỉ trả về duy nhất 1 câu truy vấn đã chuẩn hóa, không có lời mở đầu hoặc giải thích."""

CONTEXTUAL_REWRITE_SYSTEM_PROMPT = """Bạn là chuyên gia chuẩn hóa truy vấn tra cứu pháp luật Việt Nam trong hội thoại nhiều lượt (Multi-turn Conversational RAG).
Nhiệm vụ: Dựa vào LỊCH SỬ HỘI THOẠI và CÂU HỎI MỚI NHẤT, hãy viết lại thành một CÂU HỎI ĐỘC LẬP (Standalone Query) hoàn chỉnh, chuẩn xác thuật ngữ pháp lý để phục vụ tra cứu Điều luật.

Quy tắc bắt buộc:
1. Giải quyết triệt để các đại từ thay thế (nó, việc đó, trường hợp này) và câu hỏi tỉnh lược (ví dụ: "thế còn ô tô thì sao?", "có bị tước bằng không?").
   - Ví dụ:
     + Lịch sử: User hỏi về vượt đèn đỏ xe máy -> Câu mới: "thế còn ô tô thì sao?" -> Viết lại: "Xử phạt hành vi vượt đèn đỏ đối với xe ô tô"
     + Lịch sử: Đang trao đổi về vượt đèn đỏ ô tô -> Câu mới: "có bị tước bằng lái không?" -> Viết lại: "Hình thức xử phạt tước quyền sử dụng giấy phép lái xe đối với hành vi vượt đèn đỏ xe ô tô"
     + Lịch sử: Hỏi về thời gian thử việc đại học -> Câu mới: "thế còn cao đẳng?" -> Viết lại: "Thời gian thử việc tối đa đối với người lao động có trình độ cao đẳng"
2. Nếu câu hỏi mới hoàn toàn chuyển sang chủ đề khác không liên quan đến lịch sử, chỉ chuẩn hóa câu hỏi mới độc lập.
3. KHÔNG tự ý bịa đặt số Điều, số Khoản nếu câu hỏi không nêu.
4. Chỉ trả về DUY NHẤT 1 câu truy vấn độc lập đã chuẩn hóa, không có lời dẫn hoặc giải thích."""


class QueryRewriter:
    """Bộ viết lại câu hỏi đời thường thành thuật ngữ pháp lý bằng LLM (hỗ trợ đa lượt hội thoại)."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.settings = get_settings()
        self.llm = llm or LLMClient()

    async def rewrite(self, query: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        """Chuẩn hóa câu hỏi đời thường thành thuật ngữ pháp lý quy chuẩn, có giải quyết quy chiếu nếu có lịch sử."""
        clean_query = query.strip()
        if not clean_query:
            return query

        try:
            # Nếu có lịch sử hội thoại, kích hoạt Contextual Query Rewriter (Coreference Resolution)
            if history and len(history) > 0:
                # Lấy tối đa 3 lượt đối thoại gần nhất (tối đa 6 tin nhắn) để tránh quá tải ngữ cảnh
                recent_history = history[-6:]
                history_lines = []
                for msg in recent_history:
                    role_label = "Người dùng" if msg.get("role") == "user" else "Trợ lý"
                    content_snippet = msg.get("content", "").strip().split("\n")[0][:150]
                    history_lines.append(f"{role_label}: {content_snippet}")
                history_str = "\n".join(history_lines)

                prompt = (
                    f"[LỊCH SỬ HỘI THOẠI]:\n{history_str}\n\n"
                    f"[CÂU HỎI MỚI NHẤT]:\n{clean_query}\n\n"
                    f"Truy vấn độc lập chuẩn hóa:"
                )
                messages = [
                    {"role": "system", "content": CONTEXTUAL_REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            else:
                messages = [
                    {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Câu hỏi: {clean_query}\nTruy vấn chuẩn hóa:"},
                ]

            resp = await self.llm.generate(messages, temperature=0.0)
            rewritten = resp.strip().strip('"').strip("'")
            rewritten = re.sub(r"^(truy vấn chuẩn hóa:|câu hỏi chuẩn hóa:|viết lại:|truy vấn độc lập chuẩn hóa:)\s*", "", rewritten, flags=re.I).strip()

            if rewritten and len(rewritten) > 5:
                logger.info(f"[QueryRewriter] '{query}' -> '{rewritten}'")
                return rewritten
        except Exception as e:
            logger.warning(f"[QueryRewriter] Lỗi viết lại truy vấn ({e}), dùng lại query gốc.")

        return query
