"""Kiểm thử tự động toàn diện kiến trúc Agentic RAG (Self-RAG & Corrective RAG - CRAG)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.agent.graph import LegalAgent
from src.agent.state import LegalAgentState


async def test_agentic_rag_flows():
    print("=== BẮT ĐẦU KIỂM THỬ TOÀN DIỆN KIẾN TRÚC AGENTIC RAG ===")

    # 1. Khởi tạo mock LLM và mock Retriever
    mock_llm = MagicMock()
    mock_retriever = MagicMock()
    mock_retriever.initialize = AsyncMock()

    # Tạo LegalAgent với mock
    agent = LegalAgent(retriever=mock_retriever, llm=mock_llm)

    # -------------------------------------------------------------
    # TEST 1: Kiểm tra Intent Routing (Smalltalk)
    # -------------------------------------------------------------
    print("\n[TEST 1] Kiểm tra nhánh Smalltalk...")
    mock_llm.generate = AsyncMock(return_value="smalltalk")
    res1 = await agent.invoke("Chào bạn, bạn là ai thế?")
    assert res1.get("intent") == "smalltalk", f"Expected smalltalk, got {res1.get('intent')}"
    print("-> PASS: Intent router chuyển đúng sang smalltalk_node!")

    # -------------------------------------------------------------
    # TEST 2: Kiểm tra Luồng Agentic RAG Chuẩn mực (Happy Path)
    # -------------------------------------------------------------
    print("\n[TEST 2] Kiểm tra luồng Agentic RAG tiêu chuẩn (Decompose -> Retrieve -> Grade -> Generate -> Guard)...")
    mock_docs = [
        {
            "id": 1,
            "law_id": "100/2019/NĐ-CP",
            "law_name": "Nghị định 100/2019/NĐ-CP",
            "article": "Điều 5",
            "article_title": "Xử phạt người điều khiển xe ô tô vi phạm quy tắc giao thông",
            "content": "1. Phạt tiền từ 200.000 đồng đến 400.000 đồng đối với hành vi sau đây:\na) Không chấp hành hiệu lệnh, chỉ dẫn của biển báo hiệu, vạch kẻ đường.",
            "rerank_score": 0.85,
        }
    ]

    # Cấu hình chuỗi phản hồi của LLM:
    # Lần 1: Router -> "legal_query"
    # Lần 2: Spell/Decompose -> Trả về JSON sub-queries
    # Lần 3: HyDE -> Sinh đoạn giả định
    # Lần 4: Generate -> Sinh câu trả lời chuẩn 4 phần
    async def side_effect_generate(messages, **kwargs):
        content = messages[-1].get("content", "")
        system = messages[0].get("content", "")
        if "phân loại ý định" in system.lower() or "intent" in system.lower():
            return "legal_query"
        elif "phân rã" in system.lower() or "decompose" in system.lower():
            return '{"is_multi_violation": false, "standalone_query": "mức phạt không chấp hành biển báo", "sub_queries": ["mức phạt không chấp hành biển báo"]}'
        elif "quy chuẩn thuật ngữ" in system.lower() or "hyde" in system.lower():
            return "Quy định về xử phạt vi phạm hành chính đối với hành vi không chấp hành biển báo."
        else:
            return (
                "### 1. Kết luận\nHành vi không chấp hành biển báo hiệu bị phạt tiền từ 200.000 đến 400.000 đồng.\n\n"
                "### 2. Căn cứ pháp lý\n- Điều 5 Nghị định 100/2019/NĐ-CP.\n\n"
                "### 3. Phân tích & Chi tiết áp dụng\nTheo Điểm a Khoản 1 Điều 5, mức phạt áp dụng là 200.000 - 400.000 đồng.\n\n"
                "### 4. Hướng dẫn & Lưu ý thực tiễn\nNgười tham gia giao thông cần chú ý quan sát biển báo hiệu đường bộ.\n\n"
                "[GỢI Ý CÂU HỎI TIẾP THEO]:\n- Lỗi này có bị tước bằng lái không?\n- Thời hạn nộp phạt là bao lâu?"
            )

    mock_llm.generate = AsyncMock(side_effect=side_effect_generate)
    mock_retriever.search = AsyncMock(return_value=mock_docs)

    res2 = await agent.invoke("Không chấp hành biển báo phạt bao nhiêu?")
    assert res2.get("intent") == "legal_query"
    assert res2.get("docs_grade") == "relevant", f"Expected relevant, got {res2.get('docs_grade')}"
    assert res2.get("guard_status") == "passed", f"Expected passed, got {res2.get('guard_status')}"
    assert "### 1. Kết luận" in res2.get("answer")
    assert len(res2.get("citations", [])) > 0
    print("-> PASS: Agentic RAG tiêu chuẩn hoàn thành trơn tru với đầy đủ 4 phần và trích dẫn chuẩn!")

    # -------------------------------------------------------------
    # TEST 3: Kiểm tra Vòng lặp 1: Corrective RAG (CRAG) khi tài liệu ban đầu không khớp
    # -------------------------------------------------------------
    print("\n[TEST 3] Kiểm tra Vòng lặp 1: Corrective RAG (Tài liệu không khớp -> Tự Rewrite -> Tìm lại)...")
    call_count = {"search": 0}

    async def mock_search_crag(*args, **kwargs):
        call_count["search"] += 1
        if call_count["search"] == 1:
            # Lần 1: Trả về tài liệu không liên quan (điểm cực thấp)
            return [{
                "id": 99,
                "law_id": "01/2020",
                "law_name": "Luật Hàng không",
                "article": "Điều 99",
                "article_title": "Tàu bay dân dụng",
                "content": "Quy định về đăng kiểm tàu bay và chứng chỉ bay.",
                "rerank_score": 0.01,
            }]
        else:
            # Lần 2 (sau khi rewrite): Trả về tài liệu chính xác
            return mock_docs

    mock_retriever.search = AsyncMock(side_effect=mock_search_crag)

    res3 = await agent.invoke("Lỗi không theo biển hiệu")
    assert call_count["search"] >= 2, f"Expected at least 2 searches via CRAG loop, got {call_count['search']}"
    assert res3.get("retry_count", 0) >= 1, "Expected retry_count >= 1 for CRAG loop"
    print(f"-> PASS: Vòng lặp CRAG hoạt động chính xác! Đã tự động Rewrite và tìm kiếm lại (Số lần tìm kiếm: {call_count['search']}).")

    # -------------------------------------------------------------
    # TEST 4: Kiểm tra Vòng lặp 2: Self-Correction (Self-RAG) khi LLM bịa Điều luật
    # -------------------------------------------------------------
    print("\n[TEST 4] Kiểm tra Vòng lặp 2: Self-RAG (Phát hiện trích dẫn ảo -> Tự gửi feedback -> Sinh lại)...")
    gen_count = {"generate": 0}

    async def side_effect_self_rag(messages, **kwargs):
        content = messages[-1].get("content", "")
        system = messages[0].get("content", "")
        if "phân loại ý định" in system.lower() or "intent" in system.lower():
            return "legal_query"
        elif "phân rã" in system.lower() or "decompose" in system.lower():
            return '{"is_multi_violation": false, "standalone_query": "mức phạt vượt đèn đỏ", "sub_queries": ["mức phạt vượt đèn đỏ"]}'
        elif "quy chuẩn thuật ngữ" in system.lower() or "hyde" in system.lower():
            return "Quy định xử phạt đèn đỏ."
        else:
            gen_count["generate"] += 1
            if gen_count["generate"] == 1:
                # Lần 1: LLM bịa ra "Điều 888" không có trong context (Điều 5)
                return (
                    "### 1. Kết luận\nPhạt tiền 1.000.000 đồng.\n\n"
                    "### 2. Căn cứ pháp lý\nTheo Điều 888 Luật Giao thông tưởng tượng.\n\n"
                    "### 3. Phân tích & Chi tiết áp dụng\nQuy định tại Điều 888.\n\n"
                    "### 4. Hướng dẫn & Lưu ý thực tiễn\nNộp phạt tại kho bạc."
                )
            else:
                # Lần 2 (sau feedback): LLM sửa lại trích dẫn đúng Điều 5 có trong context
                assert "[CẢNH BÁO KIỂM ĐỊNH TRÍCH DẪN" in content, "Expected feedback instruction in prompt!"
                return (
                    "### 1. Kết luận\nPhạt tiền theo quy định pháp luật.\n\n"
                    "### 2. Căn cứ pháp lý\nTheo Điều 5 Nghị định 100/2019/NĐ-CP.\n\n"
                    "### 3. Phân tích & Chi tiết áp dụng\nÁp dụng Điều 5.\n\n"
                    "### 4. Hướng dẫn & Lưu ý thực tiễn\nCần chấp hành hiệu lệnh."
                )

    mock_llm.generate = AsyncMock(side_effect=side_effect_self_rag)
    mock_retriever.search = AsyncMock(return_value=mock_docs)

    res4 = await agent.invoke("Vượt đèn đỏ phạt thế nào?")
    assert gen_count["generate"] >= 2, f"Expected at least 2 generations via Self-RAG loop, got {gen_count['generate']}"
    assert res4.get("guard_status") == "passed", f"Expected passed after correction, got {res4.get('guard_status')}"
    print(f"-> PASS: Vòng lặp Self-RAG hoạt động hoàn hảo! Đã phát hiện Điều 888 ảo giác, tự động feedback và LLM đã sinh lại chính xác (Số lần sinh: {gen_count['generate']}).")

    print("\n=============================================================")
    print("🎉 TẤT CẢ CÁC BÀI KIỂM THỬ AGENTIC RAG ĐÃ VƯỢT QUA 100%!")
    print("=============================================================")


if __name__ == "__main__":
    asyncio.run(test_agentic_rag_flows())
