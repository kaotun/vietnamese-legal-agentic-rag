"""Module chuẩn hóa văn bản tiếng Việt (Lớp 1 – Text Normalizer).
Xử lý Unicode NFC, khoảng trắng thừa và phát hiện văn bản thiếu dấu bằng underthesea.
"""
from __future__ import annotations

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)

# Cố gắng import underthesea; fallback gracefully nếu chưa cài
try:
    from underthesea import text_normalize
    _UNDERTHESEA_AVAILABLE = True
except ImportError:
    _UNDERTHESEA_AVAILABLE = False
    logger.warning("[TextNormalizer] underthesea chưa được cài đặt. Chỉ dùng Unicode normalization.")


def _has_vietnamese_tones(text: str) -> bool:
    """Kiểm tra xem văn bản có chứa dấu thanh tiếng Việt không."""
    viet_toned = set("àáâãèéêìíòóôõùúýăđơưạảấầẩẫắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ"
                     "ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐƠƯẠẢẤẦẨẪẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỶỸỴ")
    text_chars = set(text)
    return bool(text_chars & viet_toned)


def _ratio_toned(text: str) -> float:
    """Tỷ lệ ký tự chữ cái có dấu thanh trên tổng ký tự chữ cái."""
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return 1.0
    viet_toned = set("àáâãèéêìíòóôõùúýăđơưạảấầẩẫắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỷỹỵ"
                     "ÀÁÂÃÈÉÊÌÍÒÓÔÕÙÚÝĂĐƠƯẠẢẤẦẨẪẮẰẲẴẶẸẺẼẾỀỂỄỆỈỊỌỎỐỒỔỖỘỚỜỞỠỢỤỦỨỪỬỮỰỲỶỸỴ")
    toned = sum(1 for c in letters if c in viet_toned)
    return toned / len(letters)


def normalize_text(text: str) -> tuple[str, bool]:
    """Chuẩn hóa văn bản tiếng Việt.

    Returns:
        (normalized_text, was_modified): văn bản đã chuẩn hóa và flag có thay đổi hay không.
    """
    original = text

    # 1. Chuẩn hóa Unicode NFC (tránh tổ hợp dấu khác nhau)
    text = unicodedata.normalize("NFC", text)

    # 2. Xóa ký tự điều khiển, chuẩn hóa khoảng trắng
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"[ \t]+", " ", text).strip()

    # 3. underthesea text_normalize: chuẩn hóa số, đơn vị, dấu câu tiếng Việt
    if _UNDERTHESEA_AVAILABLE:
        try:
            text = text_normalize(text)
        except Exception as e:
            logger.debug(f"[TextNormalizer] underthesea text_normalize lỗi: {e}")

    was_modified = text.strip() != original.strip()
    if was_modified:
        logger.info(f"[TextNormalizer] '{original}' -> '{text}'")

    return text, was_modified


def detect_no_tone(text: str, threshold: float = 0.05) -> bool:
    """Phát hiện văn bản có khả năng bị thiếu dấu thanh (gõ không dấu).

    Args:
        threshold: Nếu tỷ lệ ký tự có dấu < threshold thì coi là không dấu.
    """
    # Nếu văn bản rất ngắn (<= 3 từ) thì không đáng tin cậy để phán đoán
    words = text.strip().split()
    if len(words) <= 3:
        return False

    ratio = _ratio_toned(text)
    is_no_tone = ratio < threshold
    if is_no_tone:
        logger.info(f"[TextNormalizer] Phát hiện văn bản thiếu dấu (ratio={ratio:.2f}): '{text[:60]}...'")
    return is_no_tone
