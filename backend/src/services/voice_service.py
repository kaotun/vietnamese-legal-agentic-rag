"""Dịch vụ chuyển đổi văn bản câu trả lời thành giọng nói tiếng Việt tự nhiên (TTS) qua Microsoft Edge-TTS."""
from __future__ import annotations

import logging
import re
from typing import AsyncGenerator
import edge_tts

logger = logging.getLogger(__name__)

# Giọng đọc chuẩn tiếng Việt hỗ trợ bởi Microsoft Edge-TTS
DEFAULT_VOICE = "vi-VN-HoaiMyNeural"  # Giọng Nữ truyền cảm
VOICE_MALE = "vi-VN-NamMinhNeural"    # Giọng Nam trầm ấm, rõ ràng


def clean_text_for_tts(text: str, max_chars: int = 800) -> str:
    """Lọc bỏ các ký tự Markdown, phần gợi ý câu hỏi và định dạng đặc biệt để giọng đọc tự nhiên, súc tích."""
    if not text:
        return ""

    # Loại bỏ danh sách gợi ý câu hỏi tiếp theo ở cuối câu trả lời
    cleaned = re.split(r"\[GỢI Ý CÂU HỎI TIẾP THEO\]", text, flags=re.IGNORECASE)[0]

    # Loại bỏ code blocks ```...```
    cleaned = re.sub(r"```[\s\S]*?```", "", cleaned)
    # Loại bỏ inline code `...`
    cleaned = re.sub(r"`.*?`", "", cleaned)
    # Thay thế tiêu đề markdown (# ## ###) thành dấu chấm ngắt câu
    cleaned = re.sub(r"#+\s*", "", cleaned)
    # Loại bỏ định dạng in đậm / in nghiêng (* hoặc _)
    cleaned = re.sub(r"[\*_]{1,3}(.*?)[\*_]{1,3}", r"\1", cleaned)
    # Loại bỏ link markdown [text](url) -> giữ lại text
    cleaned = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", cleaned)
    # Loại bỏ blockquote (> )
    cleaned = re.sub(r"^\s*>\s*", "", cleaned, flags=re.MULTILINE)
    # Thay thế dấu gạch đầu dòng / bullet bằng khoảng trắng ngắt câu
    cleaned = re.sub(r"^\s*[\-\*\+]\s+", ". ", cleaned, flags=re.MULTILINE)
    # Thay thế các số thứ tự 1. 2. bằng số
    cleaned = re.sub(r"^\s*\d+\.\s+", ". ", cleaned, flags=re.MULTILINE)
    # Chuẩn hóa khoảng trắng và dấu ngắt dòng
    cleaned = re.sub(r"\n+", ". ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\.+", ".", cleaned)
    # Loại bỏ dấu câu ở đầu chuỗi (tránh lỗi NoAudioReceived trên Edge-TTS)
    cleaned = re.sub(r"^[\s\.\,\;\:\?\!\-]+", "", cleaned).strip()

    # Cắt gọn độ dài tối ưu nếu văn bản quá dài để tránh phát sinh độ trễ mạng quốc tế
    if len(cleaned) > max_chars:
        cutoff = cleaned[:max_chars].rfind(".")
        if cutoff > max_chars // 2:
            cleaned = cleaned[:cutoff + 1]
        else:
            cleaned = cleaned[:max_chars] + "..."

    return cleaned


async def text_to_speech_bytes(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> bytes:
    """Chuyển đổi văn bản thành dữ liệu âm thanh MP3 dưới dạng raw bytes."""
    sanitized_text = clean_text_for_tts(text)
    if not sanitized_text:
        raise ValueError("Văn bản sau khi làm sạch bị trống, không thể tạo âm thanh.")

    communicate = edge_tts.Communicate(
        text=sanitized_text,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )

    audio_buffer = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio_buffer.extend(chunk["data"])

    logger.info(f"Đã tạo âm thanh TTS ({len(audio_buffer)} bytes) với giọng '{voice}'")
    return bytes(audio_buffer)


async def stream_text_to_speech(
    text: str,
    voice: str = DEFAULT_VOICE,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> AsyncGenerator[bytes, None]:
    """Stream dữ liệu âm thanh MP3 theo từng chunk để phát ngay lập tức trên frontend (giảm TTFT)."""
    sanitized_text = clean_text_for_tts(text)
    if not sanitized_text:
        return

    communicate = edge_tts.Communicate(
        text=sanitized_text,
        voice=voice,
        rate=rate,
        pitch=pitch,
    )

    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            yield chunk["data"]
