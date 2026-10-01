"""Backward-compatible shim for src.retrieval.db_pool.

Database pool hiện đã được chuyển vào hạ tầng dùng chung tại `src.core.database`.
File này giữ lại để đảm bảo tương thích ngược cho toàn bộ codebase.
"""
from src.core.database import DatabasePool, get_db_pool  # noqa: F401

__all__ = ["DatabasePool", "get_db_pool"]
