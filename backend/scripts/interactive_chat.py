"""Script trò chuyện trực tiếp (Interactive CLI Chat) với Trợ lý Pháp luật Việt Nam."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from src.agent.graph import LegalAgent


async def main() -> None:
    print("=" * 75)
    print("⚖️   TRỢ LÝ PHÁP LUẬT VIỆT NAM (INTERACTIVE CLI CHAT)")
    print("    - Tích hợp HyDE & Cross-Encoder Reranker")
    print("    - Kiểm định trích dẫn an toàn qua Citation Guard")
    print("    - Gõ 'exit', 'quit' hoặc nhấn Ctrl+C để thoát")
    print("=" * 75)

    print("\n⏳ Đang khởi tạo Agent và nạp dữ liệu luật...")
    agent = LegalAgent()
    await agent.retriever.initialize()
    print("✅ Hệ thống đã sẵn sàng! Mời bạn nhập câu hỏi bên dưới.\n")

    while True:
        try:
            query = input("\n👤 Công dân hỏi > ").strip()
            if not query:
                continue
            if query.lower() in ("exit", "quit", "q"):
                print("\nCảm ơn bạn đã sử dụng Trợ lý Pháp luật. Tạm biệt!")
                break

            print("\n⏳ Trợ lý đang phân loại ý định, tra cứu luật và đối chiếu...")
            result = await agent.invoke(query)

            intent = result.get("intent", "unknown")
            guard = result.get("guard_status", "passed")
            citations = result.get("citations", [])

            print("\n" + "-" * 75)
            print(f"📌 Phân loại: [{intent}] | 🛡️ Citation Guard: [{guard}]")
            if citations:
                print(f"📚 Căn cứ tìm thấy ({len(citations)} Điều luật):")
                for c in citations:
                    print(f"   • {c}")
            print("-" * 75)
            print(f"\n⚖️  TRẢ LỜI:\n\n{result.get('answer', '').strip()}")
            print("=" * 75)

        except (KeyboardInterrupt, EOFError):
            print("\n\nCảm ơn bạn đã sử dụng Trợ lý Pháp luật. Tạm biệt!")
            break


if __name__ == "__main__":
    asyncio.run(main())
