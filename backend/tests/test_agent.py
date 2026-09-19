"""Script kiểm thử hoạt động của LangGraph LegalAgent (Phase 4)."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from src.agent.graph import LegalAgent


async def main() -> None:
    print("Khởi tạo Legal Agent (LangGraph)...")
    agent = LegalAgent()
    await agent.retriever.initialize()

    test_cases = [
        ("Xin chào bạn!", "Kỳ vọng: Nhánh smalltalk"),
        ("Hôm nay thời tiết Hà Nội thế nào bạn?", "Kỳ vọng: Nhánh out_of_scope"),
        ("Thời gian nghỉ việc hưởng chế độ thai sản khi sinh con", "Kỳ vọng: Nhánh legal_query"),
    ]

    for query, expectation in test_cases:
        print(f"\n=================================================================")
        print(f"TEST: '{query}'")
        print(f"MỤC TIÊU: {expectation}")
        print(f"-----------------------------------------------------------------")
        result = await agent.invoke(query)
        print(f"-> Phân loại Intent: [{result.get('intent')}]")
        print(f"-> Trạng thái Guard: [{result.get('guard_status')}]")
        print(f"-> Số trích dẫn tìm thấy: {len(result.get('retrieved_docs', []))}")
        print(f"-> Câu trả lời:\n{result.get('answer')}")


if __name__ == "__main__":
    asyncio.run(main())
