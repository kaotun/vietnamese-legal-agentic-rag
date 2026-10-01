"""Backward-compatible shim for src.config.

Tất cả cấu hình hệ thống hiện được quản lý tại `src.core.config`.
File này giữ lại để đảm bảo tương thích ngược cho các module hiện tại.
"""
from src.core.config import *  # noqa: F401, F403
from src.core.config import get_settings, Settings  # Explicit exports for type checkers
