"""Quản lý kết nối cơ sở dữ liệu PostgreSQL tập trung thông qua ThreadedConnectionPool.

Tối ưu hóa hiệu năng cho môi trường xử lý đồng thời (concurrency), loại bỏ chi phí
bắt tay TCP (handshake) lặp lại liên tục và ngăn chặn rò rỉ socket/connection.
"""
from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Generator, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)


class DatabasePool:
    """Singleton quản lý pool kết nối PostgreSQL dùng chung cho toàn bộ ứng dụng."""

    _instance: Optional[DatabasePool] = None

    def __init__(self, dsn: Optional[str] = None, minconn: int = 2, maxconn: int = 20):
        if not dsn:
            from src.core.config import get_settings
            dsn = get_settings().legal_assistant.postgres.database_url

        self.dsn = dsn
        self.minconn = minconn
        self.maxconn = maxconn
        self._pool: Optional[ThreadedConnectionPool] = None
        self._init_pool()

    def _init_pool(self) -> None:
        try:
            self._pool = ThreadedConnectionPool(
                minconn=self.minconn,
                maxconn=self.maxconn,
                dsn=self.dsn
            )
            logger.info(f"[DatabasePool] Khởi tạo thành công pool kết nối PostgreSQL ({self.minconn}-{self.maxconn} conn).")
        except Exception as e:
            logger.error(f"[DatabasePool] Lỗi khởi tạo connection pool: {e}")
            self._pool = None

    @classmethod
    def get_instance(cls, dsn: Optional[str] = None) -> DatabasePool:
        if cls._instance is None:
            cls._instance = cls(dsn)
        return cls._instance

    @contextmanager
    def get_connection(self) -> Generator[psycopg2.extensions.connection, None, None]:
        """Context manager mượn kết nối từ pool và tự động hoàn trả khi hoàn tất."""
        if self._pool is None:
            # Fallback tạo kết nối trực tiếp nếu pool khởi tạo thất bại
            conn = psycopg2.connect(self.dsn)
            try:
                yield conn
            finally:
                conn.close()
            return

        conn = self._pool.getconn()
        try:
            yield conn
        finally:
            self._pool.putconn(conn)

    @contextmanager
    def get_cursor(self, commit: bool = False, dict_cursor: bool = True) -> Generator[Any, None, None]:
        """Context manager cấp phát cursor và tự động commit / rollback an toàn."""
        factory = RealDictCursor if dict_cursor else None
        with self.get_connection() as conn:
            cur = conn.cursor(cursor_factory=factory)
            try:
                yield cur
                if commit:
                    conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cur.close()

    def close_all(self) -> None:
        """Đóng toàn bộ pool khi tắt ứng dụng."""
        if self._pool:
            self._pool.closeall()
            logger.info("[DatabasePool] Đã đóng toàn bộ kết nối trong pool.")


def get_db_pool(dsn: Optional[str] = None) -> DatabasePool:
    return DatabasePool.get_instance(dsn)

