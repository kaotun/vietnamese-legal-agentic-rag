"""Client gọi LLM theo chuẩn OpenAI-compatible (POST /v1/chat/completions)."""
from __future__ import annotations

import json
import logging
from typing import AsyncGenerator, Dict, List
import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


class LLMServiceError(Exception):
    """Ngoại lệ khi dịch vụ LLM không phản hồi hoặc gặp sự cố mạng/model."""
    pass


class LLMClient:
    """Client giao tiếp với mô hình ngôn ngữ lớn (LLM)."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.llm.base_url.rstrip("/")
        self.default_model = settings.llm.default_model
        self.temperature = settings.llm.temperature
        self.max_tokens = settings.llm.max_tokens
        self.api_key = settings.llm.api_key
        # Timeout riêng: connect 10s, nhưng read 180s để đủ thời gian stream token dài
        self._timeout_normal = httpx.Timeout(60.0)
        self._timeout_stream = httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=5.0)
        self.client = httpx.AsyncClient(timeout=self._timeout_normal)

    async def generate(self, messages: List[Dict[str, str]], temperature: float | None = None) -> str:
        """Gửi prompt và nhận câu trả lời đồng bộ."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.default_model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
            "frequency_penalty": 0.4,
            "presence_penalty": 0.2,
            "options": {
                "repeat_penalty": 1.18,
                "repeat_last_n": 128,
            },
        }

        try:
            resp = await self.client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"[LLMClient] Lỗi kết nối LLM ({url}): {e}")
            raise LLMServiceError(f"Không thể kết nối tới LLM endpoint ({self.base_url}): {e}") from e

    async def generate_stream(self, messages: List[Dict[str, str]]) -> AsyncGenerator[str, None]:
        """Stream token câu trả lời qua SSE."""
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        payload = {
            "model": self.default_model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "frequency_penalty": 0.4,
            "presence_penalty": 0.2,
            "options": {
                "repeat_penalty": 1.18,
                "repeat_last_n": 128,
            },
            "stream": True,
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_stream).stream(
                "POST", url, headers=headers, json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and not line.endswith("[DONE]"):
                        try:
                            chunk = json.loads(line[6:])
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
                        except Exception:
                            continue
        except Exception as e:
            logger.error(f"[LLMClient] Lỗi stream từ LLM ({url}): {e}")
            raise LLMServiceError(f"Lỗi stream từ LLM ({self.base_url}): {e}") from e

    async def close(self) -> None:
        """Đóng kết nối HTTP client an toàn."""
        if not self.client.is_closed:
            await self.client.aclose()
            logger.info("[LLMClient] Đã đóng httpx client.")
