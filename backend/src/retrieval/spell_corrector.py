"""Module sửa lỗi chính tả tiếng Việt bằng LLM (Lớp 2 – Spell Corrector).
Phát hiện và sửa lỗi chính tả / gõ sai trong ngữ cảnh pháp luật trước khi vào QueryRewriter.
"""
from __future__ import annotations

import logging
import re
from typing import Optional, List, Dict

from src.agent.llm_client import LLMClient
from src.retrieval.text_normalizer import normalize_text, detect_no_tone

logger = logging.getLogger(__name__)

SPELL_CORRECT_SYSTEM_PROMPT = """Bạn là chuyên gia ngôn ngữ tiếng Việt, chuyên sửa lỗi chính tả và lỗi gõ phím.
Nhiệm vụ: Phát hiện và sửa lỗi chính tả, lỗi gõ sai trong câu hỏi pháp luật tiếng Việt.

Quy tắc bắt buộc:
1. Chỉ sửa lỗi chính tả và lỗi gõ sai (gõ nhầm phím, thiếu dấu, sai dấu thanh).
2. KHÔNG thay đổi ý nghĩa, KHÔNG chuẩn hóa thuật ngữ pháp lý, KHÔNG thêm thông tin mới.
3. Giữ nguyên các từ viết tắt, tên riêng, số liệu.
4. Nếu câu không có lỗi chính tả, trả về NGUYÊN VĂN câu đó.
5. Chỉ trả về câu đã sửa, không giải thích, không có lời dẫn."""

NO_TONE_SYSTEM_PROMPT = """Bạn là chuyên gia ngôn ngữ tiếng Việt.
Nhiệm vụ: Thêm dấu thanh điệu tiếng Việt vào câu được gõ không dấu dưới đây.

Quy tắc:
1. Thêm đúng dấu thanh điệu cho từng từ dựa trên ngữ cảnh câu.
2. Ưu tiên đọc nghĩa câu theo ngữ cảnh pháp luật Việt Nam.
3. KHÔNG thay đổi ý nghĩa hay thêm thông tin mới.
4. Chỉ trả về câu đã thêm dấu, không giải thích."""


def _needs_spell_check(text: str) -> bool:
    """Phát hiện nhanh các dấu hiệu cần sửa lỗi chính tả để tiết kiệm LLM call."""
    # Phát hiện ký tự lạ hoặc chuỗi phụ âm bất thường
    if re.search(r"[a-zA-Z]{5,}", text):  # chuỗi Latin dài không dấu
        return True
    # Phát hiện lỗi nhân đôi ký tự: "phạtt", "tiềnn"
    if re.search(r"([a-zA-Zàáâãèéêìíòóôõùúýăđơưạảấầẩẫắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ])\1{2,}", text, re.IGNORECASE):
        return True
    return False


class SpellCorrector:
    """Sửa lỗi chính tả tiếng Việt 2 bước: Unicode normalization + LLM correction."""

    def __init__(self, llm: Optional[LLMClient] = None):
        self.llm = llm or LLMClient()

    async def correct(self, text: str) -> tuple[str, bool]:
        """Sửa lỗi chính tả văn bản đầu vào.

        Returns:
            (corrected_text, was_corrected): văn bản đã sửa và flag có thay đổi không.
        """
        if not text or not text.strip():
            return text, False

        # --- Lớp 1: Unicode normalization (underthesea) ---
        normalized, norm_changed = normalize_text(text)

        # --- Lớp 2a: Phát hiện văn bản không dấu → thêm dấu bằng LLM ---
        if detect_no_tone(normalized):
            logger.info(f"[SpellCorrector] Phát hiện văn bản không dấu, đang thêm dấu...")
            try:
                corrected = await self._add_tones(normalized)
                logger.info(f"[SpellCorrector] Thêm dấu: '{normalized}' -> '{corrected}'")
                return corrected, True
            except Exception as e:
                logger.warning(f"[SpellCorrector] Lỗi thêm dấu: {e}")
                return normalized, norm_changed

        # --- Lớp 2b: Sửa lỗi chính tả thông thường (chỉ khi có dấu hiệu lỗi) ---
        if _needs_spell_check(normalized):
            logger.info(f"[SpellCorrector] Phát hiện dấu hiệu lỗi chính tả, đang sửa...")
            try:
                corrected = await self._llm_spell_correct(normalized)
                if corrected and corrected.strip() != normalized.strip():
                    logger.info(f"[SpellCorrector] Sửa lỗi: '{normalized}' -> '{corrected}'")
                    return corrected, True
            except Exception as e:
                logger.warning(f"[SpellCorrector] Lỗi sửa chính tả LLM: {e}")

        return normalized, norm_changed

    async def _llm_spell_correct(self, text: str) -> str:
        """Dùng LLM sửa lỗi chính tả."""
        messages = [
            {"role": "system", "content": SPELL_CORRECT_SYSTEM_PROMPT},
            {"role": "user", "content": f"Câu cần kiểm tra: {text}"},
        ]
        result = await self.llm.generate(messages, temperature=0.0)
        result = result.strip().strip('"').strip("'")
        # Loại bỏ prefix LLM có thể thêm vào
        result = re.sub(
            r"^(câu đã sửa:|câu sửa lỗi:|kết quả:|câu không lỗi:)\s*",
            "", result, flags=re.IGNORECASE
        ).strip()
        return result if result else text

    async def _add_tones(self, text: str) -> str:
        """Dùng LLM thêm dấu thanh cho văn bản không dấu."""
        messages = [
            {"role": "system", "content": NO_TONE_SYSTEM_PROMPT},
            {"role": "user", "content": f"Câu không dấu: {text}"},
        ]
        result = await self.llm.generate(messages, temperature=0.0)
        result = result.strip().strip('"').strip("'")
        result = re.sub(
            r"^(câu có dấu:|kết quả:|câu đã thêm dấu:)\s*",
            "", result, flags=re.IGNORECASE
        ).strip()
        return result if result else text
