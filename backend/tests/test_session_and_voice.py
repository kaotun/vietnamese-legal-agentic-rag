"""Kịch bản kiểm thử toàn diện Quản lý Đa phiên hội thoại (Multi-session) và Giọng nói (Voice AI TTS)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

# Cấu hình UTF-8 cho Windows console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Đảm bảo đường dẫn gốc backend có trong sys.path
backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_root))

from src.agent.graph import LegalAgent
from src.agent.session_manager import SessionManager
from src.services.voice_service import text_to_speech_bytes, stream_text_to_speech, clean_text_for_tts


async def main():
    print("=" * 80)
    print("🚀 BẮT ĐẦU KIỂM THỬ ĐA PHIÊN HỘI THOẠI (MULTI-SESSION) & GIỌNG NÓI (VOICE AI)")
    print("=" * 80)

    # Khởi tạo SessionManager và Agent
    session_manager = SessionManager(storage_dir=backend_root / "data" / "sessions")
    agent = LegalAgent(session_manager=session_manager)
    await agent.retriever.initialize()

    # --------------------------------------------------------------------------
    # 1. TẠO VÀ TƯƠNG TÁC VỚI PHIÊN HỘI THOẠI THỨ NHẤT (SESSION A: Giao thông)
    # --------------------------------------------------------------------------
    print("\n--- [BƯỚC 1] TẠO PHIÊN A: CHỦ ĐỀ GIAO THÔNG ---")
    session_a = session_manager.create_session(title="Giao thông vượt đèn đỏ")
    id_a = session_a["id"]
    print(f"✅ Đã tạo Session A: ID = {id_a}, Title = '{session_a['title']}'")

    q_a1 = "Xe máy vượt đèn đỏ bị phạt bao nhiêu tiền?"
    print(f"\n💬 [Session A - Lượt 1] User: {q_a1}")
    res_a1 = await agent.invoke(query=q_a1, session_id=id_a)
    print(f"🤖 Trợ lý: {res_a1['answer'][:150]}...")
    print(f"📚 Trích dẫn: {res_a1['citations']}")

    # --------------------------------------------------------------------------
    # 2. TẠO VÀ TƯƠNG TÁC VỚI PHIÊN HỘI THOẠI THỨ HAI (SESSION B: Lao động)
    # --------------------------------------------------------------------------
    print("\n--- [BƯỚC 2] TẠO PHIÊN B: CHỦ ĐỀ LUẬT LAO ĐỘNG (HOÀN TOÀN ĐỘC LẬP) ---")
    session_b = session_manager.create_session(title="Thời gian thử việc")
    id_b = session_b["id"]
    print(f"✅ Đã tạo Session B: ID = {id_b}, Title = '{session_b['title']}'")

    q_b1 = "Thời gian thử việc tối đa là bao lâu theo quy định?"
    print(f"\n💬 [Session B - Lượt 1] User: {q_b1}")
    res_b1 = await agent.invoke(query=q_b1, session_id=id_b)
    print(f"🤖 Trợ lý: {res_b1['answer'][:150]}...")
    print(f"📚 Trích dẫn: {res_b1['citations']}")

    # --------------------------------------------------------------------------
    # 3. QUAY LẠI PHIÊN A ĐỂ HỎI TIẾP (KIỂM TRA BẢO TOÀN NGỮ CẢNH ĐỘC LẬP)
    # --------------------------------------------------------------------------
    print("\n--- [BƯỚC 3] QUAY LẠI PHIÊN A VÀ HỎI TIẾP (CÂU TỈNH LƯỢC) ---")
    q_a2 = "Thế còn ô tô thì sao?"
    print(f"💬 [Session A - Lượt 2] User: {q_a2}")
    res_a2 = await agent.invoke(query=q_a2, session_id=id_a)
    print(f"🎯 Standalone Query sinh ra: {res_a2.get('standalone_query')}")
    print(f"🤖 Trợ lý: {res_a2['answer'][:150]}...")
    print(f"📚 Trích dẫn: {res_a2['citations']}")

    # Kiểm tra Session A không bị nhiễm ngữ cảnh của Session B
    assert "thử việc" not in res_a2.get("standalone_query", "").lower(), "LỖI: Session A bị nhiễm ngữ cảnh từ Session B!"
    assert any(k in res_a2.get("standalone_query", "").lower() for k in ["ô tô", "đèn đỏ"]), "LỖI: Standalone query không đúng chủ đề!"
    print("✅ Kiểm tra cách ly ngữ cảnh (Session Isolation): XUẤT SẮC!")

    # --------------------------------------------------------------------------
    # 4. KIỂM TRA DANH SÁCH VÀ CHI TIẾT TỪ Ổ ĐĨA
    # --------------------------------------------------------------------------
    print("\n--- [BƯỚC 4] KIỂM TRA LƯU TRỮ TRÊN Ổ ĐĨA VÀ LIỆT KÊ TẤT CẢ PHIÊN ---")
    all_sessions = session_manager.list_sessions()
    print(f"📋 Tổng số phiên hiện có trên đĩa: {len(all_sessions)}")
    for s in all_sessions:
        print(f"   - [{s['id']}] '{s['title']}' (Số tin nhắn: {s['message_count']}, Lượt: {s['turn_count']})")

    detail_a = session_manager.get_session(id_a)
    assert detail_a is not None
    assert len(detail_a["messages"]) == 4, f"Session A phải có 4 tin nhắn (2 lượt), thực tế: {len(detail_a['messages'])}"
    print("✅ Kiểm tra đọc chi tiết tin nhắn Session A từ file JSON: HỢP LỆ (4 tin nhắn)!")

    # --------------------------------------------------------------------------
    # 5. KIỂM TRA XÓA PHIÊN HỘI THOẠI CŨ (SESSION B)
    # --------------------------------------------------------------------------
    print("\n--- [BƯỚC 5] KIỂM THỬ XÓA PHIÊN B ---")
    deleted = session_manager.delete_session(id_b)
    assert deleted is True, "LỖI: Không thể xóa session B"
    print(f"🗑️ Đã xóa thành công Session B: {id_b}")

    sessions_after_delete = session_manager.list_sessions()
    remaining_ids = [s["id"] for s in sessions_after_delete]
    assert id_b not in remaining_ids, "LỖI: Session B vẫn còn trong danh sách!"
    assert id_a in remaining_ids, "LỖI: Session A bị xóa nhầm!"
    print(f"✅ Sau khi xóa Session B, hệ thống còn lại Session A: {remaining_ids}")

    # --------------------------------------------------------------------------
    # 6. KIỂM THỬ TÍCH HỢP GIỌNG NÓI (VOICE AI: TTS)
    # --------------------------------------------------------------------------
    print("\n--- [BƯỚC 6] KIỂM THỬ SINH GIỌNG NÓI TIẾNG VIỆT (MICROSOFT EDGE-TTS) ---")
    # Lấy phần kết luận đầu tiên để tổng hợp giọng nói
    sample_text = res_a1["answer"].split("### 2.")[0].strip() if "### 2." in res_a1["answer"] else res_a1["answer"][:150]
    print(f"📄 Văn bản gốc: {sample_text[:100]}...")
    cleaned_tts = clean_text_for_tts(sample_text)
    print(f"🧹 Văn bản sau khi lọc markdown: {cleaned_tts[:100]}...")

    print("🔊 Đang tổng hợp giọng nói tiếng Việt chuẩn (vi-VN-HoaiMyNeural)...")
    audio_bytes = await text_to_speech_bytes(cleaned_tts, voice="vi-VN-HoaiMyNeural")
    print(f"✅ Tạo thành công file âm thanh MP3: {len(audio_bytes):,} bytes!")

    # Lưu file mẫu để có thể nghe thử
    out_audio = backend_root / "data" / "test_sample_tts.mp3"
    out_audio.write_bytes(audio_bytes)
    print(f"💾 Đã lưu file âm thanh mẫu tại: {out_audio}")

    # Kiểm tra streaming TTS chunks
    stream_chunks = 0
    total_stream_bytes = 0
    async for chunk in stream_text_to_speech("Xin chào bạn, tôi là trợ lý pháp lý AI."):
        stream_chunks += 1
        total_stream_bytes += len(chunk)
    print(f"✅ Kiểm thử TTS Streaming: Nhận thành công {stream_chunks} audio chunks ({total_stream_bytes} bytes)!")

    print("\n" + "=" * 80)
    print("🎉 TẤT CẢ CÁC BƯỚC KIỂM THỬ ĐÃ HOÀN TẤT VÀ VƯỢT QUA 100%!")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(main())
