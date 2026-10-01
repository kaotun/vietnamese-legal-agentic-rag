# -*- coding: utf-8 -*-
"""Dịch vụ chuyển đổi văn bản câu trả lời thành giọng nói tiếng Việt tự nhiên (TTS).

Hỗ trợ 2 chế độ vận hành:
1. "edge-tts" (mặc định): Sử dụng Microsoft Edge-TTS trực tuyến với chất lượng giọng đọc tự nhiên, truyền cảm.
2. "local_http": Kết nối tới máy chủ TTS nội bộ (Piper TTS / Kokoro / LocalAI) phục vụ mạng nội bộ cách ly (Air-Gapped / 100% Offline).
"""
from __future__ import annotations

import asyncio
import logging
import re
from typing import AsyncGenerator
import edge_tts
import httpx

from src.core.config import get_settings

logger = logging.getLogger(__name__)

# Giọng đọc chuẩn tiếng Việt hỗ trợ bởi Microsoft Edge-TTS
DEFAULT_VOICE = "vi-VN-HoaiMyNeural"  # Giọng Nữ truyền cảm
VOICE_MALE = "vi-VN-NamMinhNeural"    # Giọng Nam trầm ấm, rõ ràng
LOCAL_VOICE = "vi-vn-local"           # Giọng nội bộ cho Local TTS


class OfflineVoiceError(RuntimeError):
    """Ngoại lệ phát sinh khi Voice AI không thể kết nối tới dịch vụ TTS trong môi trường offline / mạng cách ly."""
    pass


def _is_network_or_offline_error(exc: Exception) -> bool:
    """Kiểm tra xem ngoại lệ có phải do lỗi kết nối mạng / DNS / máy chủ ngoại vi offline hay không."""
    err_str = str(exc).lower()
    type_name = type(exc).__name__.lower()

    network_indicators = [
        "gaierror",
        "getaddrinfo failed",
        "clientconnectorerror",
        "cannot connect",
        "connection refused",
        "connection reset",
        "network is unreachable",
        "no route to host",
        "timed out",
        "timeout",
        "handshake",
        "websocket",
        "no audioreceived",
        "no audio received",
        "connectionerror",
    ]
    if any(ind in err_str or ind in type_name for ind in network_indicators):
        return True
    if isinstance(exc, (OSError, TimeoutError, ConnectionError)):
        return True
    return False


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
    # Thay thế dấu gạch đầu dòng / bullet bằng khoảng trống ngắt câu
    cleaned = re.sub(r"^\s*[\-\*\+]\s+", ". ", cleaned, flags=re.MULTILINE)
    # Thay thế các số thứ tự 1. 2. bằng số
    cleaned = re.sub(r"^\s*\d+\.\s+", ". ", cleaned, flags=re.MULTILINE)
    # Chuẩn hóa khoảng trắng và dấu ngắt dòng
    cleaned = re.sub(r"\n+", ". ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\.+", ".", cleaned)
    # Loại bỏ dấu câu ở đầu chuỗi (tránh lỗi NoAudioReceived trên Edge-TTS)
    cleaned = re.sub(r"^[\s\.\,\;\:\?\!\-]+", "", cleaned).strip()

    # Cắt gọn độ dài tối ưu nếu văn bản quá dài theo ranh giới câu hoặc từ
    if len(cleaned) > max_chars:
        cutoff = cleaned[:max_chars].rfind(".")
        if cutoff > max_chars // 2:
            cleaned = cleaned[:cutoff + 1]
        else:
            # Tìm khoảng trắng gần nhất để không cắt đứt từ UTF-8
            space_cutoff = cleaned[:max_chars].rfind(" ")
            if space_cutoff > 0:
                cleaned = cleaned[:space_cutoff] + "."
            else:
                cleaned = cleaned[:max_chars]

    return cleaned.strip()


async def _synthesize_local_http(
    text: str,
    voice: str,
    base_url: str,
) -> bytes:
    """Gọi HTTP endpoint của mô hình TTS nội bộ (Piper TTS / Kokoro / LocalAI) hỗ trợ chuẩn OpenAI-compatible."""
    payload = {
        "model": "tts-1",
        "input": text,
        "voice": voice,
        "response_format": "mp3",
    }
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(base_url, json=payload)
            if resp.status_code != 200:
                raise OfflineVoiceError(
                    f"Máy chủ Local TTS ({base_url}) trả về mã lỗi HTTP {resp.status_code}: {resp.text[:200]}"
                )
            return resp.content
    except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as err:
        raise OfflineVoiceError(
            f"Không thể kết nối tới máy chủ Local TTS tại '{base_url}'. "
            f"Khi triển khai mạng cách ly (Air-Gapped), vui lòng khởi động dịch vụ Local TTS (Piper TTS/Kokoro) "
            f"hoặc kiểm tra lại tham số 'tts.base_url' trong config.yaml ({err})."
        ) from err
    except Exception as err:
        if isinstance(err, OfflineVoiceError):
            raise
        raise OfflineVoiceError(f"Lỗi bất thường từ Local TTS ({base_url}): {err}") from err


async def text_to_speech_bytes(
    text: str,
    voice: str | None = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> bytes:
    """Chuyển đổi văn bản thành dữ liệu âm thanh MP3 dưới dạng raw bytes (hỗ trợ Edge-TTS và Local TTS)."""
    sanitized_text = clean_text_for_tts(text)
    if not sanitized_text:
        raise ValueError("Văn bản sau khi làm sạch bị trống, không thể tạo âm thanh.")

    settings = get_settings()
    tts_cfg = settings.legal_assistant.tts
    if not tts_cfg.enabled:
        raise OfflineVoiceError("Dịch vụ Voice AI (TTS) đã bị vô hiệu hóa trong config.yaml.")

    selected_voice = voice or tts_cfg.default_voice or DEFAULT_VOICE
    provider = (tts_cfg.provider or "edge-tts").lower().strip()

    # Nhánh 1: Local HTTP TTS (hoàn toàn On-Premise / Mạng cách ly)
    if provider in ("local_http", "local", "piper", "kokoro"):
        logger.info(f"Đang tạo âm thanh qua Local TTS ({tts_cfg.base_url}) với giọng '{selected_voice}'")
        return await _synthesize_local_http(
            text=sanitized_text,
            voice=selected_voice,
            base_url=tts_cfg.base_url,
        )

    # Nhánh 2: Microsoft Edge-TTS (Trực tuyến chất lượng cao)
    try:
        communicate = edge_tts.Communicate(
            text=sanitized_text,
            voice=selected_voice,
            rate=rate,
            pitch=pitch,
        )

        audio_buffer = bytearray()
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                audio_buffer.extend(chunk["data"])

        if not audio_buffer:
            raise OfflineVoiceError(
                "Edge-TTS không trả về dữ liệu âm thanh. Kiểm tra lại kết nối mạng hoặc nội dung văn bản."
            )

        logger.info(f"Đã tạo âm thanh TTS ({len(audio_buffer)} bytes) với giọng '{selected_voice}' qua Edge-TTS")
        return bytes(audio_buffer)

    except Exception as e:
        if _is_network_or_offline_error(e):
            logger.warning(f"Lỗi mạng khi kết nối tới Microsoft Edge-TTS: {e}")
            raise OfflineVoiceError(
                f"Không thể kết nối máy chủ Microsoft Edge-TTS do không có kết nối Internet / Mạng cách ly ({type(e).__name__}). "
                "Để sử dụng Voice AI trong mạng nội bộ hoàn toàn không có internet, vui lòng đặt 'tts.provider: local_http' "
                "trong config.yaml (kết hợp Piper TTS / Kokoro) hoặc sử dụng Web Speech API cục bộ của trình duyệt."
            ) from e

        # Fallback thử lại một lần với câu tóm lược nếu lỗi nội dung/formatting
        logger.warning(f"Edge-TTS gặp lỗi ({e}), thực hiện retry với câu tóm lược...")
        fallback_text = sanitized_text.split(".")[0] if "." in sanitized_text else sanitized_text[:80]
        try:
            communicate = edge_tts.Communicate(text=fallback_text, voice=selected_voice)
            audio_buffer = bytearray()
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    audio_buffer.extend(chunk["data"])
            return bytes(audio_buffer)
        except Exception as retry_err:
            if _is_network_or_offline_error(retry_err):
                raise OfflineVoiceError(
                    f"Không thể kết nối máy chủ Microsoft Edge-TTS do máy đang Offline ({retry_err}). "
                    "Vui lòng chuyển sang 'tts.provider: local_http' hoặc tắt Voice AI."
                ) from retry_err
            raise RuntimeError(f"Lỗi tạo âm thanh với Edge-TTS: {retry_err}") from retry_err


async def stream_text_to_speech(
    text: str,
    voice: str | None = None,
    rate: str = "+0%",
    pitch: str = "+0Hz",
) -> AsyncGenerator[bytes, None]:
    """Stream dữ liệu âm thanh MP3 theo từng chunk để phát ngay lập tức trên frontend (giảm TTFT)."""
    sanitized_text = clean_text_for_tts(text)
    if not sanitized_text:
        return

    settings = get_settings()
    tts_cfg = settings.legal_assistant.tts
    if not tts_cfg.enabled:
        raise OfflineVoiceError("Dịch vụ Voice AI (TTS) đã bị vô hiệu hóa trong config.yaml.")

    selected_voice = voice or tts_cfg.default_voice or DEFAULT_VOICE
    provider = (tts_cfg.provider or "edge-tts").lower().strip()

    if provider in ("local_http", "local", "piper", "kokoro"):
        audio_data = await _synthesize_local_http(
            text=sanitized_text,
            voice=selected_voice,
            base_url=tts_cfg.base_url,
        )
        chunk_size = 4096
        for i in range(0, len(audio_data), chunk_size):
            yield audio_data[i : i + chunk_size]
        return

    # Edge-TTS streaming
    try:
        communicate = edge_tts.Communicate(
            text=sanitized_text,
            voice=selected_voice,
            rate=rate,
            pitch=pitch,
        )

        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                yield chunk["data"]
    except Exception as e:
        if _is_network_or_offline_error(e):
            logger.warning(f"Lỗi mạng khi stream Edge-TTS: {e}")
            raise OfflineVoiceError(
                f"Mất kết nối tới máy chủ Edge-TTS (môi trường mạng Offline / Mạng cách ly): {e}."
            ) from e
        raise
