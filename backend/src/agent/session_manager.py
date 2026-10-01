"""Quản lý các phiên hội thoại (Multi-session Chat Management) và lưu trữ bền vững.

Áp dụng chuẩn Enterprise:
  - Atomic File Replacement (chống race condition và file corruption khi crash giữa chừng).
  - Fine-grained Per-Session Locking (chống xung đột khi nhiều request ghi đồng thời).
  - Tự động fallback và làm sạch file tạm.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """Quản lý CRUD các phiên hội thoại được lưu trữ trên ổ đĩa (Persistent Storage)."""

    def __init__(self, storage_dir: str | Path | None = None):
        if storage_dir is None:
            backend_root = Path(__file__).resolve().parent.parent.parent
            self.storage_dir = backend_root / "data" / "sessions"
        else:
            self.storage_dir = Path(storage_dir)

        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._locks: dict[str, threading.Lock] = {}
        self._global_lock = threading.Lock()

    def _get_lock(self, session_id: str) -> threading.Lock:
        """Lấy lock tương ứng cho từng session cụ thể để tránh xung đột concurrent."""
        clean_id = self._clean_session_id(session_id)
        with self._global_lock:
            if clean_id not in self._locks:
                self._locks[clean_id] = threading.Lock()
            return self._locks[clean_id]

    def _clean_session_id(self, session_id: str) -> str:
        """Chuẩn hóa session_id an toàn cho tên file hệ thống."""
        clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "", session_id)
        return clean_id if clean_id else "default"

    def _get_session_path(self, session_id: str) -> Path:
        """Trả về đường dẫn file json của phiên hội thoại."""
        clean_id = self._clean_session_id(session_id)
        return self.storage_dir / f"{clean_id}.json"

    def _atomic_write(self, path: Path, data: dict[str, Any]) -> None:
        """Ghi dữ liệu JSON nguyên tử (Atomic write pattern).

        Ghi vào file tạm trước, flush + sync xuống đĩa cứng, sau đó dùng os.replace()
        để hoán đổi file đích tức thời. Không bao giờ để lại file json bị đọc dở hoặc hỏng.
        """
        temp_path = path.parent / f"{path.stem}_{uuid.uuid4().hex[:8]}.tmp"
        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_path, path)
        except Exception as e:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass
            logger.error(f"[SessionManager] Lỗi atomic write cho file {path}: {e}")
            raise

    def create_session(self, title: str | None = None, session_id: str | None = None) -> dict[str, Any]:
        """Tạo một phiên trò chuyện mới hoàn toàn độc lập."""
        s_id = session_id or f"sess_{uuid.uuid4().hex[:12]}"
        now = datetime.now().isoformat()
        session_data = {
            "id": s_id,
            "title": title or "Cuộc hội thoại mới",
            "created_at": now,
            "updated_at": now,
            "messages": [],
            "metadata": {
                "turn_count": 0,
            },
        }
        path = self._get_session_path(s_id)
        with self._get_lock(s_id):
            self._atomic_write(path, session_data)

        logger.info(f"Đã tạo session mới: {s_id} - '{session_data['title']}'")
        return session_data

    def list_sessions(self) -> list[dict[str, Any]]:
        """Lấy danh sách tóm tắt tất cả các phiên hội thoại, sắp xếp mới nhất trước."""
        sessions = []
        for file in self.storage_dir.glob("*.json"):
            try:
                if file.stat().st_size == 0:
                    continue
                with open(file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    messages = data.get("messages", [])
                    turn_count = data.get("metadata", {}).get("turn_count", len(messages) // 2)
                    sessions.append({
                        "id": data.get("id", file.stem),
                        "title": data.get("title", "Cuộc hội thoại"),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "message_count": len(messages),
                        "turn_count": turn_count,
                        "last_snippet": messages[-1].get("content", "")[:80] if messages else "",
                    })
            except Exception as e:
                logger.warning(f"Không thể đọc file session {file}: {e}")

        sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
        return sessions

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Lấy toàn bộ chi tiết và lịch sử tin nhắn của 1 phiên hội thoại (Thread-safe)."""
        path = self._get_session_path(session_id)
        if not path.exists():
            return None

        with self._get_lock(session_id):
            try:
                if path.stat().st_size == 0:
                    return None
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Lỗi đọc session {session_id}: {e}")
                return None

    def get_or_create_session(self, session_id: str, title: str | None = None) -> dict[str, Any]:
        """Lấy session nếu đã có, hoặc tạo mới nếu chưa tồn tại."""
        existing = self.get_session(session_id)
        if existing:
            return existing
        return self.create_session(title=title, session_id=session_id)

    def save_turn(
        self,
        session_id: str,
        user_query: str,
        assistant_answer: str,
        intent: str = "legal_query",
        citations: list[str] | None = None,
        standalone_query: str | None = None,
        followup_questions: list[str] | None = None,
        retrieved_docs: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Lưu thêm một lượt hỏi - đáp (turn) vào phiên hội thoại một cách nguyên tử."""
        now = datetime.now().isoformat()
        path = self._get_session_path(session_id)

        with self._get_lock(session_id):
            session = None
            if path.exists() and path.stat().st_size > 0:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        session = json.load(f)
                except Exception as e:
                    logger.warning(f"Lỗi đọc khi save_turn cho session {session_id}: {e}")

            if not session:
                session = {
                    "id": session_id,
                    "title": "Cuộc hội thoại mới",
                    "created_at": now,
                    "updated_at": now,
                    "messages": [],
                    "metadata": {"turn_count": 0},
                }

            # Tự động cập nhật tiêu đề nếu vẫn là tiêu đề mặc định
            current_title = session.get("title", "")
            if current_title in ["Cuộc hội thoại mới", "Đoạn chat mới", "default", "Default Session"] or not current_title:
                clean_title = user_query.strip().replace("\n", " ")
                if len(clean_title) > 40:
                    clean_title = clean_title[:37] + "..."
                session["title"] = clean_title

            user_msg = {
                "role": "user",
                "content": user_query,
                "timestamp": now,
            }
            assistant_msg = {
                "role": "assistant",
                "content": assistant_answer,
                "intent": intent,
                "citations": citations or [],
                "standalone_query": standalone_query,
                "followup_questions": followup_questions or [],
                "retrieved_docs": retrieved_docs or [],
                "timestamp": now,
            }

            session.setdefault("messages", []).extend([user_msg, assistant_msg])
            session["updated_at"] = now
            session.setdefault("metadata", {})
            session["metadata"]["turn_count"] = len(session["messages"]) // 2

            self._atomic_write(path, session)

        return session

    def rename_session(self, session_id: str, new_title: str) -> dict[str, Any] | None:
        """Đổi tên tiêu đề của một phiên hội thoại đã lưu (Thread-safe & Atomic)."""
        path = self._get_session_path(session_id)
        with self._get_lock(session_id):
            session = None
            if path.exists() and path.stat().st_size > 0:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        session = json.load(f)
                except Exception as e:
                    logger.error(f"Lỗi đọc khi đổi tên session {session_id}: {e}")

            if not session:
                return None

            clean_title = new_title.strip() or "Cuộc hội thoại"
            session["title"] = clean_title
            session["updated_at"] = datetime.now().isoformat()
            self._atomic_write(path, session)

        logger.info(f"Đã đổi tên session {session_id} thành: '{clean_title}'")
        return session

    def delete_session(self, session_id: str) -> bool:
        """Xóa vĩnh viễn một phiên hội thoại cũ (Thread-safe & Idempotent)."""
        path = self._get_session_path(session_id)
        with self._get_lock(session_id):
            if path.exists():
                try:
                    path.unlink()
                    logger.info(f"Đã xóa session thành công: {session_id}")
                    return True
                except Exception as e:
                    logger.error(f"Lỗi khi xóa session {session_id}: {e}")
                    return False
        return True

    def clear_all(self) -> int:
        """Xóa toàn bộ lịch sử các phiên hội thoại."""
        deleted_count = 0
        with self._global_lock:
            for file in self.storage_dir.glob("*.json"):
                try:
                    file.unlink()
                    deleted_count += 1
                except Exception as e:
                    logger.error(f"Không thể xóa file session {file}: {e}")
        logger.info(f"Đã dọn dẹp sạch sẽ {deleted_count} phiên hội thoại.")
        return deleted_count
