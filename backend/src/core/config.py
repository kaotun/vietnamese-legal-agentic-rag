from __future__ import annotations

import os
from pathlib import Path
from typing import Any
import yaml
from pydantic import BaseModel, Field


class AppConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://localhost:5173",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:5173",
        ]
    )


class UIConfig(BaseModel):
    host: str = "0.0.0.0"
    port: int = 3000


class LLMConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    default_model: str = "qwen2.5:3b"
    temperature: float = 0.1
    max_tokens: int = 2000
    api_key: str = "ollama"


class EmbeddingsConfig(BaseModel):
    base_url: str = "http://localhost:11434/v1"
    model: str = "nomic-embed-text"
    api_key: str = "ollama"


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
    engine: str = "smart_fallback"  # "smart_fallback" | "flashrank" | "http"
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


class TTSConfig(BaseModel):
    enabled: bool = True
    provider: str = "edge-tts"  # "edge-tts" (online chất lượng cao) | "local_http" (offline 100% cho mạng cách ly)
    base_url: str = "http://localhost:8028/v1/audio/speech"
    default_voice: str = "vi-VN-HoaiMyNeural"


class PostgresConfig(BaseModel):
    database_url: str = "postgresql://postgres:postgres@localhost:23432/legal_assistant"


class LegalAssistantConfig(BaseModel):
    chat: ChatConfig = Field(default_factory=ChatConfig)
    retrieval: RetrievalConfig = Field(default_factory=RetrievalConfig)
    hyde: HydeConfig = Field(default_factory=HydeConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    tts: TTSConfig = Field(default_factory=TTSConfig)
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
    """Tìm config.yaml từ biến môi trường hoặc các thư mục cha."""
    env_path = os.environ.get("CONFIG_PATH")
    if env_path and Path(env_path).is_file():
        return Path(env_path)

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
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        _settings = Settings(**data)

    # --------------------------------------------------------------------------
    # Đọc ghi đè từ biến môi trường (Environment Variable Overrides)
    # Rất quan trọng khi chạy trong Docker container và hệ thống CI/CD
    # --------------------------------------------------------------------------
    db_env = os.environ.get("DATABASE_URL") or os.environ.get("POSTGRES_DATABASE_URL")
    if db_env:
        _settings.legal_assistant.postgres.database_url = db_env

    ollama_env = os.environ.get("OLLAMA_BASE_URL") or os.environ.get("LLM_BASE_URL")
    if ollama_env:
        _settings.llm.base_url = ollama_env
        _settings.embeddings.base_url = ollama_env

    llm_model_env = os.environ.get("LLM_MODEL") or os.environ.get("DEFAULT_MODEL")
    if llm_model_env:
        _settings.llm.default_model = llm_model_env

    embed_model_env = os.environ.get("EMBEDDING_MODEL")
    if embed_model_env:
        _settings.embeddings.model = embed_model_env

    cors_env = os.environ.get("CORS_ORIGINS")
    if cors_env:
        _settings.app.cors_origins = [o.strip() for o in cors_env.split(",") if o.strip()]

    return _settings
