"""Kiểm tra chức năng truy hồi Hybrid Retrieval trên 13,744 records."""
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

from src.retrieval.hybrid_retriever import HybridLegalRetriever


async def main() -> None:
    print("Khởi tạo Hybrid Retriever từ PostgreSQL...")
    retriever = HybridLegalRetriever()
    await retriever.initialize()

    test_queries = [
        "Thời gian nghỉ việc hưởng chế độ thai sản của lao động nữ",
        "Các hành vi bị nghiêm cấm trong hỗ trợ doanh nghiệp nhỏ và vừa",
        "Điều kiện được cấp Giấy chứng nhận quyền sử dụng đất",
    ]

    for q in test_queries:
        print(f"\n========================================================")
        print(f"CÂU HỎI: {q}")
        print(f"========================================================")
        results = await retriever.search(q, top_k=2)
        if not results:
            print("  Không tìm thấy kết quả phù hợp.")
            continue

        for i, r in enumerate(results, 1):
            law_name = r.get("law_name", "")
            article = r.get("article", "")
            title = r.get("article_title", "")
            content = r.get("content", "").replace("\n", " ")[:150]
            print(f"Top {i}: [{law_name}] - {article}: {title}")
            print(f"       Nội dung: {content}...")


if __name__ == "__main__":
    asyncio.run(main())
