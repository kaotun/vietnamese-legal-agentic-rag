"""Module tạo Hypothetical Document Embeddings (HyDE) cho truy vấn pháp luật Việt Nam."""
from __future__ import annotations

import logging
import re
from typing import Optional

from src.agent.llm_client import LLMClient
from src.config import get_settings

logger = logging.getLogger(__name__)

HYDE_LEGAL_SYSTEM_PROMPT = """Bạn là chuyên gia soạn thảo và quy chuẩn thuật ngữ pháp luật Việt Nam.
Nhiệm vụ của bạn: Từ câu hỏi thông thường của công dân, hãy viết một đoạn văn bản quy chuẩn (3-5 câu) mô phỏng nội dung điều luật quy định về vấn đề đó để phục vụ tìm kiếm ngữ nghĩa (embedding search).

Quy tắc bắt buộc:
1. Sử dụng văn phong hành chính - pháp lý chuẩn mực (quy định về nghĩa vụ, hành vi bị nghiêm cấm, điều kiện áp dụng, mức độ chế tài hoặc xử phạt).
2. KHÔNG bịa đặt số Điều, số Khoản, mã Nghị định hay Luật cụ thể (ví dụ: không ghi 'Theo Điều 5 Nghị định 100...').
3. Dùng danh xưng và thuật ngữ chính thống (ví dụ: 'người điều khiển xe mô tô, xe gắn máy' thay cho 'đi xe máy', 'không chấp hành hiệu lệnh của đèn tín hiệu giao thông' thay cho 'vượt đèn đỏ').
4. Chỉ trả về duy nhất đoạn văn bản mô phỏng, không giải thích thêm, không có lời mở đầu như 'Dưới đây là...'."""


class HydeGenerator:
    """Bộ tạo văn bản giả định (HyDE) trước khi embedding và truy hồi."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.settings = get_settings()
        self.llm = llm or LLMClient()
        self.enabled = self.settings.legal_assistant.hyde.enabled

    async def generate_hypothetical_passage(self, query: str) -> str:
        """Sinh đoạn văn bản pháp lý giả định từ câu hỏi của người dùng."""
        if not self.enabled:
            return query

        clean_query = query.strip()
        if not clean_query:
            return query

        try:
            messages = [
                {"role": "system", "content": HYDE_LEGAL_SYSTEM_PROMPT},
                {"role": "user", "content": f"Câu hỏi của công dân: {clean_query}\nVăn bản quy định mô phỏng:"},
            ]

            resp = await self.llm.generate(
                messages,
                temperature=self.settings.legal_assistant.hyde.temperature,
            )

            passage = resp.strip()
            # Loại bỏ các tiền tố giải thích thừa nếu có
            passage = re.sub(r"^(dưới đây là|văn bản mô phỏng:|đoạn văn:|theo quy định:|trích dẫn:)\s*", "", passage, flags=re.I)
            passage = passage.strip().strip('"').strip("'")

            if passage and len(passage) > 20:
                logger.info(f"[HyDE] Đã tạo passage giả định ({len(passage)} ký tự) cho query: '{query[:40]}...'")
                return passage

        except Exception as e:
            logger.warning(f"[HyDE] Sinh văn bản giả định thất bại ({e}), fallback về query gốc.")

        return query
