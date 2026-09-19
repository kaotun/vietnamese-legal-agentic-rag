"""Quản lý các phiên hội thoại (Multi-session Chat Management) và lưu trữ bền vững."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class SessionManager:
    """Quản lý CRUD các phiên hội thoại được lưu trữ trên ổ đĩa (Persistent Storage)."""

    def __init__(self, storage_dir: str | Path | None = None):
        if storage_dir is None:
            # Mặc định lưu tại thư mục data/sessions tương đối với backend root
            backend_root = Path(__file__).resolve().parent.parent.parent
            self.storage_dir = backend_root / "data" / "sessions"
        else:
            self.storage_dir = Path(storage_dir)

        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def _get_session_path(self, session_id: str) -> Path:
        """Chuẩn hóa session_id và trả về đường dẫn file json."""
        clean_id = re.sub(r"[^a-zA-Z0-9_\-]", "", session_id)
        if not clean_id:
            clean_id = "default"
        return self.storage_dir / f"{clean_id}.json"

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
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session_data, f, ensure_ascii=False, indent=2)

        logger.info(f"Đã tạo session mới: {s_id} - '{session_data['title']}'")
        return session_data

    def list_sessions(self) -> list[dict[str, Any]]:
        """Lấy danh sách tóm tắt tất cả các phiên hội thoại, sắp xếp mới nhất trước."""
        sessions = []
        for file in self.storage_dir.glob("*.json"):
            try:
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

        # Sắp xếp theo updated_at giảm dần
        sessions.sort(key=lambda s: s.get("updated_at") or "", reverse=True)
        return sessions

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        """Lấy toàn bộ chi tiết và lịch sử tin nhắn của 1 phiên hội thoại."""
        path = self._get_session_path(session_id)
        if not path.exists():
            return None
        try:
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
        """Lưu thêm một lượt hỏi - đáp (turn) vào phiên hội thoại."""
        session = self.get_or_create_session(session_id)
        now = datetime.now().isoformat()

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

        path = self._get_session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        return session

    def rename_session(self, session_id: str, new_title: str) -> dict[str, Any] | None:
        """Đổi tên tiêu đề của một phiên hội thoại đã lưu."""
        session = self.get_session(session_id)
        if not session:
            return None
        clean_title = new_title.strip()
        if not clean_title:
            clean_title = "Cuộc hội thoại"
        session["title"] = clean_title
        session["updated_at"] = datetime.now().isoformat()

        path = self._get_session_path(session_id)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(session, f, ensure_ascii=False, indent=2)

        logger.info(f"Đã đổi tên session {session_id} thành: '{clean_title}'")
        return session

    def delete_session(self, session_id: str) -> bool:
        """Xóa vĩnh viễn một phiên hội thoại cũ."""
        path = self._get_session_path(session_id)
        if path.exists():
            try:
                path.unlink()
                logger.info(f"Đã xóa session thành công: {session_id}")
                return True
            except Exception as e:
                logger.error(f"Lỗi khi xóa session {session_id}: {e}")
                return False
        return False

    def clear_all(self) -> int:
        """Xóa toàn bộ lịch sử các phiên hội thoại."""
        deleted_count = 0
        for file in self.storage_dir.glob("*.json"):
            try:
                file.unlink()
                deleted_count += 1
            except Exception as e:
                logger.error(f"Không thể xóa file session {file}: {e}")
        logger.info(f"Đã dọn dẹp sạch sẽ {deleted_count} phiên hội thoại.")
        return deleted_count
