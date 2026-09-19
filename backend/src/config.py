from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000


class UIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 5173


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:8024/v1"
    default_model: str = "qwen2.5-14b-instruct"
    temperature: float = 0.0
    max_tokens: int = 3000
    api_key: str = "sk-no-key-required"


class EmbeddingsConfig(BaseModel):
    base_url: str = "http://localhost:8026/v1"
    model: str = "bge-m3"
    api_key: str = "sk-no-key-required"


class ChatConfig(BaseModel):
    streaming: bool = True
    token_streaming: bool = True


class RetrievalConfig(BaseModel):
    top_k: int = 20
    rerank_top_k: int = 5
    fusion_method: str = "rrf"


class HydeConfig(BaseModel):
    enabled: bool = True
    max_tokens: int = 300
    temperature: float = 0.1


class RerankerConfig(BaseModel):
    enabled: bool = True
    engine: str = "flashrank"  # "flashrank" | "http" | "smart_fallback"
    model: str = "ms-marco-MiniLM-L-12-v2"
    base_url: str = "http://localhost:8025"
    endpoint: str = "/v1/rerank"
    api_key: str = "sk-no-key-required"
    top_n: int = 5


class BatchEvalConfig(BaseModel):
    enabled: bool = False
    max_concurrency: int = 4
    save_outputs: bool = True
    output_dir: str = "./outputs"


class PostgresConfig(BaseModel):
    database_url: str = "postgresql://postgres:postgres@localhost:23432/legal_assistant"


class LegalAssistantConfig(BaseModel):
    chat: ChatConfig = Field(default_factory=ChatConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    hyde: HydeConfig = Field(default_factory=HydeConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    batch_eval: BatchEvalConfig = Field(default_factory=BatchEvalConfig)
    postgres: PostgresConfig = Field(default_factory=PostgresConfig)


class Settings(BaseModel):
    app: AppConfig = Field(default_factory=AppConfig)
    ui: UIConfig = Field(default_factory=UIConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    embeddings: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)
    legal_assistant: LegalAssistantConfig = Field(default_factory=LegalAssistantConfig)


_settings: Settings | None = None


def find_config_yaml() -> Path:
    """Tìm config.yaml từ các thư mục cha."""
    cur = Path(__file__).resolve().parent
    for _ in range(5):
        candidate = cur / "config.yaml"
        if candidate.is_file():
            return candidate
        if (cur / "legal-qa-system" / "config.yaml").is_file():
            return cur / "legal-qa-system" / "config.yaml"
        cur = cur.parent
    # Fallback to current working directory
    return Path.cwd() / "config.yaml"


def get_settings(reload: bool = False) -> Settings:
    global _settings
    if _settings is not None and not reload:
        return _settings

    config_path = find_config_yaml()
    if not config_path.exists():
        _settings = Settings()
        return _settings

    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    _settings = Settings(**data)
    return _settings
