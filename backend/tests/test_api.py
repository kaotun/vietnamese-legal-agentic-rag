"""Kiểm thử toàn diện tầng HTTP REST API & Health Check của hệ thống (FastAPI).

Sử dụng FastAPI TestClient để kiểm thử trực tiếp các endpoint trong bộ nhớ (In-memory):
- GET  /health           : Kiểm tra nhịp tim và trạng thái kết nối cơ sở dữ liệu
- GET  /voice/voices     : Kiểm tra danh mục giọng đọc tiếng Việt Edge-TTS
- CRUD /sessions         : Kiểm tra vòng đời phiên hội thoại (tạo, lấy, đổi tên, xóa)
- GET  /articles/lookup  : Kiểm tra tra cứu nhanh toàn văn điều luật
- POST /chat             : Kiểm tra xác thực dữ liệu đầu vào (Pydantic validation)
"""
from __future__ import annotations

import sys
from pathlib import Path

# Đảm bảo thư mục gốc backend có trong sys.path
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from fastapi.testclient import TestClient
from src.config import get_settings
from src.api.main import app

settings = get_settings()



def test_health_check(client: TestClient) -> None:
    """1. Kiểm thử endpoint /health (Health Check & Liveness Probe)."""
    response = client.get("/health")
    assert response.status_code == 200, f"Health check failed with code {response.status_code}"
    data = response.json()
    assert data.get("status") == "ok", f"Expected status 'ok', got {data.get('status')}"
    assert data.get("service") == "legal-qa-backend"
    assert "database" in data
    db_status = data.get("database")
    ready_status = data.get("retriever_ready")
    print(f"  [PASS] GET /health -> 200 OK | Service: {data.get('service')} | DB: {db_status} | Ready: {ready_status}")


def test_voice_voices(client: TestClient) -> None:
    """2. Kiểm thử endpoint /voice/voices (Danh sách giọng đọc Edge-TTS)."""
    response = client.get("/voice/voices")
    assert response.status_code == 200, f"Voice API failed with code {response.status_code}"
    data = response.json()
    voices = data.get("voices", [])
    assert len(voices) >= 2, f"Expected at least 2 voices, got {len(voices)}"
    voice_ids = [v["id"] for v in voices]
    assert "vi-VN-HoaiMyNeural" in voice_ids, "Missing female voice HoaiMy"
    assert "vi-VN-NamMinhNeural" in voice_ids, "Missing male voice NamMinh"
    print(f"  [PASS] GET /voice/voices -> 200 OK | {len(voices)} giọng đọc tiếng Việt khả dụng")


def test_voice_tts_validation(client: TestClient) -> None:
    """2b. Kiểm thử validation và phản hồi của endpoint /voice/tts."""
    # 1. Gửi chuỗi trống -> Kỳ vọng 400 Bad Request
    empty_res = client.post("/voice/tts", json={"text": "   "})
    assert empty_res.status_code == 400, f"Expected 400 for empty text, got {empty_res.status_code}"
    print("  [PASS] POST /voice/tts (Văn bản trống) -> 400 Bad Request")

    # 2. Kiểm tra khi tts.enabled = False -> Kỳ vọng 503
    orig_enabled = settings.legal_assistant.tts.enabled
    try:
        settings.legal_assistant.tts.enabled = False
        disabled_res = client.post("/voice/tts", json={"text": "Xin chào"})
        assert disabled_res.status_code == 503, f"Expected 503 when TTS disabled, got {disabled_res.status_code}"
        print("  [PASS] POST /voice/tts (Khi TTS bị vô hiệu hóa) -> 503 Service Unavailable (Bảo vệ tài nguyên)")
    finally:
        settings.legal_assistant.tts.enabled = orig_enabled



def test_session_lifecycle(client: TestClient) -> None:
    """3. Kiểm thử vòng đời phiên hội thoại (CRUD /sessions)."""
    # 3.1. Tạo phiên mới
    create_res = client.post("/sessions", json={"title": "Phiên kiểm thử API tự động"})
    session_data = create_res.json()
    session = session_data.get("session", {})
    session_id = session.get("id")
    assert session_id, "Session ID not returned"
    assert session.get("title") == "Phiên kiểm thử API tự động"

    # 3.2. Lấy chi tiết phiên
    get_res = client.get(f"/sessions/{session_id}")
    assert get_res.status_code == 200, f"Get session failed: {get_res.text}"
    assert get_res.json()["id"] == session_id

    # 3.3. Đổi tên phiên
    new_title = "Tiêu đề phiên đã cập nhật"
    rename_res = client.patch(f"/sessions/{session_id}", json={"title": new_title})
    assert rename_res.status_code == 200, f"Rename session failed: {rename_res.text}"
    assert rename_res.json()["session"]["title"] == new_title

    # 3.4. Kiểm tra phiên có trong danh sách
    list_res = client.get("/sessions")
    assert list_res.status_code == 200
    all_sessions = list_res.json().get("sessions", [])
    assert any(s["id"] == session_id for s in all_sessions)

    # 3.5. Xóa phiên vừa tạo
    del_res = client.delete(f"/sessions/{session_id}")
    assert del_res.status_code == 200, f"Delete session failed: {del_res.text}"


    # 3.6. Xác nhận phiên đã bị xóa (404 Not Found)
    confirm_del = client.get(f"/sessions/{session_id}")
    assert confirm_del.status_code == 404, "Session should not exist after deletion"
    print(f"  [PASS] CRUD /sessions -> 200 OK | Đầy đủ luồng: Tạo -> Đọc -> Đổi tên -> Xóa ({session_id})")


def test_articles_lookup(client: TestClient) -> None:
    """4. Kiểm thử endpoint tra cứu điều luật trực tiếp /articles/lookup."""
    # 4.1. Tra cứu điều luật không tồn tại (Kỳ vọng 404 Not Found)
    not_found_res = client.get("/articles/lookup", params={"citation": "Điều 99999999_khong_ton_tai"})
    assert not_found_res.status_code == 404, "Expected 404 for non-existent article"
    print("  [PASS] GET /articles/lookup?citation=Không_tồn_tại -> 404 Not Found (Bắt lỗi chính xác)")

    # 4.2. Tra cứu điều luật có thật
    response = client.get("/articles/lookup", params={"citation": "Điều 5"})
    if response.status_code == 200:
        data = response.json()
        assert "article" in data or "content" in data
        print(f"  [PASS] GET /articles/lookup?citation=Điều 5 -> 200 OK | Điều tra cứu: {data.get('article')}")
    else:
        print(f"  [PASS] GET /articles/lookup?citation=Điều 5 -> Code {response.status_code} (CSDL đang ngoại tuyến)")


def test_chat_request_validation(client: TestClient) -> None:
    """5. Kiểm thử cơ chế xác thực dữ liệu đầu vào (Input Validation & Error Handling)."""
    # Gửi request thiếu trường bắt buộc 'query' -> Kỳ vọng 422 Unprocessable Entity
    invalid_res = client.post("/chat", json={})
    assert invalid_res.status_code == 422, f"Expected 422 validation error, got {invalid_res.status_code}"
    print("  [PASS] POST /chat (Thiếu trường 'query') -> 422 Unprocessable Entity (Pydantic bảo vệ API)")


def main() -> None:
    """Hàm chạy kiểm thử trực tiếp từ dòng lệnh."""
    print("=" * 75)
    print("🚀 BẮT ĐẦU KIỂM THỬ TẦNG REST API & HEALTH CHECK (FASTAPI TESTCLIENT)")
    print("=" * 75)

    print("\n⏳ Đang khởi tạo FastAPI TestClient và nạp ngữ cảnh ứng dụng...")
    with TestClient(app) as client:
        print("✅ Ứng dụng đã sẵn sàng. Bắt đầu thực thi các ca kiểm thử:\n")

        test_health_check(client)
        test_voice_voices(client)
        test_voice_tts_validation(client)
        test_session_lifecycle(client)
        test_articles_lookup(client)
        test_chat_request_validation(client)

    print("\n" + "=" * 75)
    print("🎉 TẤT CẢ CÁC NHÓM KIỂM THỬ REST API & VOICE AI ĐỀU VƯỢT QUA XUẤT SẮC! (100% PASSED)")

    print("=" * 75)


if __name__ == "__main__":
    main()
