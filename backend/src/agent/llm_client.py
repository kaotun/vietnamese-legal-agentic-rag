"""Client gọi LLM theo chuẩn OpenAI-compatible (POST /v1/chat/completions)."""
from __future__ import annotations

import logging
from typing import AsyncGenerator, Dict, List
import httpx

from src.config import get_settings

logger = logging.getLogger(__name__)


class LLMClient:
    """Client giao tiếp với mô hình ngôn ngữ lớn (LLM)."""

    def __init__(self):
        settings = get_settings()
        self.base_url = settings.llm.base_url.rstrip("/")
        self.default_model = settings.llm.default_model
        self.temperature = settings.llm.temperature
        self.max_tokens = settings.llm.max_tokens
        self.api_key = settings.llm.api_key
        self.client = httpx.AsyncClient(timeout=60.0)

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
            logger.warning(f"Lỗi kết nối LLM ({url}): {e}")
            # Fallback nếu LLM server chưa bật
            return f"[Chưa thể kết nối tới LLM endpoint tại {self.base_url}. Vui lòng kiểm tra Model Serving]."

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
            async with self.client.stream("POST", url, headers=headers, json=payload) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and not line.endswith("[DONE]"):
                        import json
                        try:
                            chunk = json.loads(line[6:])
                            content = chunk["choices"][0]["delta"].get("content", "")
                            if content:
                                yield content
                        except Exception:
                            continue
        except Exception as e:
            yield f"[Lỗi stream từ LLM: {e}]"
