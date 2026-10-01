"""Module phân rã truy vấn pháp lý (Sub-query Decomposition) bằng LLM.
Tự động phát hiện câu hỏi chứa nhiều hành vi vi phạm, chuẩn hóa sang thuật ngữ pháp lý và phân rã thành các sub-queries độc lập.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from src.agent.llm_client import LLMClient
from src.core.config import get_settings

logger = logging.getLogger(__name__)

DECOMPOSE_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích và phân rã truy vấn pháp luật Việt Nam.
Nhiệm vụ: Phân tích câu hỏi của người dùng, xác định số lượng hành vi vi phạm hoặc ý định pháp lý độc lập,
và chuẩn hóa ngôn ngữ đời thường sang THUẬT NGỮ PHÁP LUẬT VIỆT NAM CHUẨN MỰC dựa trên kiến thức pháp luật của bạn.

Nguyên tắc chuẩn hóa (tự áp dụng theo kiến thức pháp luật, không phụ thuộc vào ví dụ cố định):
- Nhận diện ngôn ngữ đời thường và thay bằng thuật ngữ pháp luật chính xác theo các văn bản quy phạm pháp luật Việt Nam hiện hành.
- Đặt câu truy vấn đầy đủ theo cấu trúc: [Đối tượng] + [Hành vi] + [Lĩnh vực pháp luật liên quan].
- Ưu tiên thuật ngữ trong các bộ luật, nghị định, thông tư Việt Nam.

Quy tắc phân loại:
1. Câu hỏi CÓ 1 VẤN ĐỀ PHÁP LÝ ĐƠN LẺ:
   - "is_multi_violation": false
   - "standalone_query": Câu hỏi được chuẩn hóa sang thuật ngữ pháp luật.
   - "sub_queries": ["<standalone_query>"]

2. Câu hỏi chứa TỪ 2 HÀNH VI VI PHẠM / VẤN ĐỀ PHÁP LÝ ĐỘC LẬP TRỞ LÊN:
   - "is_multi_violation": true
   - "standalone_query": Câu truy vấn tổng hợp chuẩn hóa.
   - "sub_queries": Danh sách truy vấn con riêng biệt cho từng hành vi, chuẩn hóa theo thuật ngữ pháp luật.
   - LUÔN THÊM 1 truy vấn con về nguyên tắc xử lý khi có nhiều vi phạm cùng lúc (ví dụ: nguyên tắc xử phạt vi phạm hành chính khi thực hiện nhiều hành vi vi phạm, hoặc nguyên tắc tính hình phạt khi phạm nhiều tội - tùy lĩnh vực).

Định dạng trả về (JSON thuần túy, không kèm giải thích):
{
  "is_multi_violation": true/false,
  "standalone_query": "...",
  "sub_queries": ["...", "..."]
}
"""

CONTEXTUAL_DECOMPOSE_SYSTEM_PROMPT = """Bạn là chuyên gia phân tích và phân rã truy vấn pháp luật Việt Nam trong hội thoại nhiều lượt.
Nhiệm vụ: Dựa vào LỊCH SỬ HỘI THOẠI và CÂU HỎI MỚI NHẤT, giải quyết đại từ quy chiếu, tỉnh lược và xác định xem có bao nhiêu hành vi vi phạm hoặc ý định pháp lý.

Nguyên tắc chuẩn hóa: Dùng kiến thức pháp luật Việt Nam hiện hành để chuyển ngôn ngữ đời thường sang thuật ngữ pháp luật chuẩn mực trong các văn bản quy phạm pháp luật.

Quy tắc:
1. Giải quyết triệt để đại từ và câu hỏi tỉnh lược (nó, trường hợp này, thế còn ô tô thì sao, có bị phạt thêm gì không...).
2. Nếu câu hỏi chứa từ 2 hành vi vi phạm trở lên: "is_multi_violation": true, phân rã thành sub-queries độc lập + thêm truy vấn nguyên tắc xử lý nhiều vi phạm.
3. Nếu chỉ có 1 hành vi: "is_multi_violation": false.

Trả về duy nhất định dạng JSON (không giải thích thêm):
{
  "is_multi_violation": true/false,
  "standalone_query": "...",
  "sub_queries": ["..."]
}
"""


def normalize_legal_colloquialisms(text: str) -> str:
    """Chuẩn hóa ngôn ngữ đời thường sang thuật ngữ pháp lý chuẩn mực của Việt Nam."""
    res = text
    mappings = [
        (r"\b(?:chưa có|không có|không mang|quên)\s+bằng\s+lái\b", "không có Giấy phép lái xe"),
        (r"\b(chưa có bằng|không có bằng)\b", "không có Giấy phép lái xe"),
        (r"\bbằng\s+lái\b", "Giấy phép lái xe"),
        (r"\bvượt\s+đèn\s+đỏ\b", "không chấp hành hiệu lệnh của đèn tín hiệu giao thông"),
        (r"\b(uống\s+rượu\s+bia\s+lái\s+xe|nồng\s+độ\s+cồn)\b", "nồng độ cồn trong máu hoặc hơi thở"),
        (r"\b(bắn\s+tốc\s+độ|quá\s+tốc\s+độ|chạy\s+quá\s+tốc\s+độ)\b", "chạy quá tốc độ quy định"),
        (r"\bđi\s+ngược\s+chiều\b", "đi ngược chiều của đường một chiều"),
    ]
    for pat, repl in mappings:
        res = re.sub(pat, repl, res, flags=re.IGNORECASE)
    return res


class QueryDecomposer:
    """Bộ phân rã truy vấn tự động bằng LLM không dùng hardcode."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.settings = get_settings()
        self.llm = llm or LLMClient()

    async def decompose(
        self,
        query: str,
        history: Optional[List[Dict[str, str]]] = None,
    ) -> Dict[str, Any]:
        """Phân rã câu hỏi người dùng thành các sub-queries độc lập và gắn nhãn đa vi phạm."""
        clean_query = normalize_legal_colloquialisms(query.strip())
        if not clean_query:
            return {
                "is_multi_violation": False,
                "standalone_query": query,
                "sub_queries": [query],
            }

        try:
            if history and len(history) > 0:
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
                    f"Trả về JSON phân rã:"
                )
                messages = [
                    {"role": "system", "content": CONTEXTUAL_DECOMPOSE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ]
            else:
                messages = [
                    {"role": "system", "content": DECOMPOSE_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Câu hỏi: \"{clean_query}\"\nTrả về JSON phân rã:"},
                ]

            raw_resp = await self.llm.generate(messages, temperature=0.0)
            parsed = self._parse_json(raw_resp)

            if parsed and isinstance(parsed, dict) and "sub_queries" in parsed:
                sub_queries = [str(q).strip() for q in parsed.get("sub_queries", []) if str(q).strip()]
                if not sub_queries:
                    sub_queries = [clean_query]

                is_multi = bool(parsed.get("is_multi_violation", len(sub_queries) > 1))
                standalone = str(parsed.get("standalone_query") or clean_query).strip()

                logger.info(
                    f"[QueryDecomposer] is_multi={is_multi}, standalone='{standalone}', sub_queries={sub_queries}"
                )
                return {
                    "is_multi_violation": is_multi,
                    "standalone_query": standalone,
                    "sub_queries": sub_queries,
                }
        except Exception as e:
            logger.warning(f"[QueryDecomposer] Lỗi phân rã ({e}), fallback sang truy vấn đơn.")

        return {
            "is_multi_violation": False,
            "standalone_query": clean_query,
            "sub_queries": [clean_query],
        }

    def _parse_json(self, text: str) -> Optional[Dict[str, Any]]:
        """Bóc tách JSON an toàn từ phản hồi của LLM."""
        text = text.strip()
        # Tìm trong markdown block ```json ... ```
        match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if match:
            text = match.group(1).strip()
        else:
            # Tìm cặp dấu ngoặc nhọn đầu tiên và cuối cùng
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1 and end > start:
                text = text[start : end + 1].strip()

        try:
            return json.loads(text)
        except Exception:
            return None
